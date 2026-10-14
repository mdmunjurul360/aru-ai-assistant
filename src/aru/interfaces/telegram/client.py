"""Telethon client lifecycle manager and event binder for Telegram in ARU AI V4."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError

from aru.core.config.models import AppSettings
from aru.core.logging import StructuredLogger
from aru.interfaces.telegram.dispatcher import TelegramDispatcher
from aru.interfaces.telegram.formatter import split_message
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext


class TelegramClientManager:
    """
    Manages Telethon connection lifecycle, event binding, and outbound message splitting.
    """

    def __init__(
        self,
        settings: AppSettings,
        dispatcher: TelegramDispatcher | None = None,
        client: TelegramClient | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._settings = settings
        self._dispatcher = dispatcher or TelegramDispatcher()
        self._logger = logger or StructuredLogger("aru.telegram.client")
        self._client = client
        self._is_running = False

    @property
    def client(self) -> TelegramClient | None:
        return self._client

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected())

    async def is_authorized(self) -> bool:
        if not self._client or not self._client.is_connected():
            return False
        return await self._client.is_user_authorized()

    def _init_client(self) -> TelegramClient:
        if self._client is not None:
            return self._client

        api_id = self._settings.telegram.tg_api_id
        api_hash = self._settings.telegram.tg_api_hash.get_secret_value()
        session_path = self._settings.telegram.session_path

        # Ensure session parent directory exists
        Path(session_path).parent.mkdir(parents=True, exist_ok=True)

        self._client = TelegramClient(session_path, api_id, api_hash)
        return self._client

    def _register_listeners(self) -> None:
        """Register Telethon event handlers onto the client."""
        if not self._client:
            return

        @self._client.on(events.NewMessage())
        async def on_new_message(event: events.NewMessage.Event) -> None:
            await self._handle_new_message(event)

        @self._client.on(events.CallbackQuery())
        async def on_callback_query(event: events.CallbackQuery.Event) -> None:
            await self._handle_callback_query(event)

    async def start(self, interactive: bool = False) -> bool:
        """
        Connect to Telegram, register event listeners, and verify authorization.
        """
        client = self._init_client()
        self._logger.info("Connecting to Telegram...")
        await client.connect()

        authorized = await client.is_user_authorized()
        if not authorized:
            if interactive:
                self._logger.info("Initiating interactive terminal login...")
                await client.start()
                authorized = await client.is_user_authorized()
            else:
                self._logger.warning("Telegram client is not authorized and interactive=False.")
                return False

        if authorized:
            me = await client.get_me()
            username = getattr(me, "username", None) or getattr(me, "first_name", "Unknown")
            self._logger.info("Telegram client authorized as %s (id=%s)", username, getattr(me, "id", 0))
            self._register_listeners()
            self._is_running = True
            return True

        return False

    async def stop(self) -> None:
        """Gracefully disconnect from Telegram."""
        if self._client and self._client.is_connected():
            self._logger.info("Disconnecting Telegram client...")
            await self._client.disconnect()
        self._is_running = False

    async def _handle_new_message(self, event: events.NewMessage.Event) -> None:
        """Transform incoming Telethon message into TelegramUpdateContext and dispatch."""
        try:
            sender_id = event.sender_id or 0
            chat_id = event.chat_id or 0
            text = event.text or ""

            metadata: dict[str, Any] = {}

            # Detect voice note
            if getattr(event, "voice", None):
                metadata["is_voice"] = True
                duration = getattr(event.voice, "attributes", [None])[0]
                metadata["duration"] = getattr(duration, "duration", 0) if duration else 0

            # Detect media
            elif getattr(event, "photo", None):
                metadata["media_type"] = "image"
            elif getattr(event, "document", None):
                mime = getattr(event.document, "mime_type", "")
                if "pdf" in mime.lower():
                    metadata["media_type"] = "pdf"
                    metadata["filename"] = getattr(event.file, "name", "document.pdf")
                else:
                    metadata["media_type"] = "document"

            ctx = TelegramUpdateContext(
                event=event,
                user_id=sender_id,
                chat_id=chat_id,
                text=text,
                metadata=metadata,
            )

            await self._dispatcher.dispatch(ctx)

            if ctx.reply_text:
                await self.send_split_message(
                    chat_id=chat_id,
                    text=ctx.reply_text,
                    reply_to=event.id,
                )

        except Exception as exc:
            self._logger.error("Error handling incoming Telegram message: %s", exc, exc_info=True)

    async def _handle_callback_query(self, event: events.CallbackQuery.Event) -> None:
        """Transform incoming Telethon callback into TelegramUpdateContext and dispatch."""
        try:
            sender_id = event.sender_id or 0
            chat_id = event.chat_id or 0
            data_bytes = getattr(event, "data", b"")
            data_str = data_bytes.decode("utf-8", errors="replace") if isinstance(data_bytes, bytes) else str(data_bytes)

            ctx = TelegramUpdateContext(
                event=event,
                user_id=sender_id,
                chat_id=chat_id,
                text="",
                metadata={"callback_data": data_str},
            )

            await self._dispatcher.dispatch(ctx)

            if ctx.reply_text:
                try:
                    await event.answer(ctx.reply_text)
                except Exception:
                    await self.send_split_message(chat_id=chat_id, text=ctx.reply_text)
            else:
                await event.answer()

        except Exception as exc:
            self._logger.error("Error handling callback query: %s", exc, exc_info=True)

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_to: int | None = None,
        parse_mode: str = "md",
    ) -> Any:
        """Send a single message or automatically split if over length limit."""
        results = await self.send_split_message(chat_id=chat_id, text=text, reply_to=reply_to, parse_mode=parse_mode)
        return results[0] if results else None

    async def send_split_message(
        self,
        chat_id: int | str,
        text: str,
        reply_to: int | None = None,
        parse_mode: str = "md",
    ) -> list[Any]:
        """
        Split text into safe chunks and send sequentially to preserve code fences
        and message limits.
        """
        if not self._client or not self._client.is_connected():
            self._logger.warning("Cannot send message: Telegram client not connected")
            return []

        chunks = split_message(text)
        sent_messages: list[Any] = []

        for i, chunk in enumerate(chunks):
            # Only first chunk is tied to reply_to, subsequent are sequential
            target_reply = reply_to if i == 0 else None
            try:
                msg = await self._client.send_message(
                    entity=chat_id,
                    message=chunk,
                    reply_to=target_reply,
                    parse_mode=parse_mode,
                )
                sent_messages.append(msg)
            except FloodWaitError as fwe:
                self._logger.warning("FloodWaitError: sleeping %ds before retrying...", fwe.seconds)
                await asyncio.sleep(fwe.seconds)
                msg = await self._client.send_message(
                    entity=chat_id,
                    message=chunk,
                    reply_to=target_reply,
                    parse_mode=parse_mode,
                )
                sent_messages.append(msg)
            except RPCError as rpc_err:
                self._logger.error("Telegram RPC error sending chunk %d: %s", i + 1, rpc_err)
                break
            except Exception as exc:
                self._logger.error("Failed to send message chunk: %s", exc)
                break

        return sent_messages

    async def send_to_boss(self, text: str) -> list[Any]:
        """Send a notification or update directly to the configured Boss Telegram ID."""
        boss_id = self._settings.telegram.boss_telegram_id
        if not boss_id:
            self._logger.warning("BOSS_TELEGRAM_ID is not configured, cannot send message to boss.")
            return []
        return await self.send_split_message(chat_id=boss_id, text=text)
