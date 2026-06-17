#!/usr/bin/env python3
"""
Aru AI v2 — Personal Telegram UserBot AI Assistant
Run: python main.py
"""

from __future__ import annotations

import mimetypes
mimetypes.init()
mimetypes._db = mimetypes.MimeTypes()

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    RPCError,
    SessionPasswordNeededError,
)

from modules.activity_log import ActivityLogger
from modules.ai import AruAI
from modules.auth import unauthorized_message, verify_sender, verify_secret_code
from modules.browser import BrowserAutomation
from modules.commands import (
    handle_help_command,
    handle_memory_command,
    handle_reminder_command,
    handle_status_command,
)
from modules.config import (
    BOSS_TELEGRAM_ID,
    DATABASE_DIR,
    ENV_PATH,
    LOGS_DIR,
    ROOT_DIR,
    SESSION_PATH,
    SESSIONS_DIR,
    TG_API_HASH,
    TG_API_ID,
    env_file_status,
    reload_settings,
    validate_config,
)
from modules.logging_setup import setup_logging
from modules.memory import MemoryStore
from modules.research import ResearchAgent
from modules.scheduler import AruScheduler
from modules.tasks import TaskManager
from modules.voice import VoiceAssistant

logger = setup_logging()

BANNER = """
=====================
ARU AI v2 ONLINE
Telegram Connected
Groq Connected
Memory System Active
Voice Assistant Ready
Research Agent Ready
Boss Verification Active
=====================
"""

# Per-chat conversation history for AI context
_chat_history: dict[int, list[dict[str, str]]] = defaultdict(list)
MAX_HISTORY = 20


class AruBot:
    """Telegram UserBot orchestrator."""

    def __init__(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        self.activity = ActivityLogger()
        self.client = TelegramClient(
            str(SESSION_PATH),
            TG_API_ID,
            TG_API_HASH,
            connection_retries=10,
            retry_delay=5,
            auto_reconnect=True,
        )
        self.ai = AruAI()
        self.memory = MemoryStore(activity=self.activity)
        self.tasks = TaskManager(activity=self.activity)
        self.research = ResearchAgent(self.ai, activity=self.activity)
        self.voice = VoiceAssistant(self.ai, activity=self.activity)
        self.browser = BrowserAutomation()
        self.scheduler: AruScheduler | None = None
        self._telegram_ok = False
        self._groq_ok = False
        self._voice_ok = False

    async def send_to_boss(self, text: str) -> None:
        """Send message to Boss (scheduled jobs, reports)."""
        if not BOSS_TELEGRAM_ID:
            return
        try:
            await self.client.send_message(BOSS_TELEGRAM_ID, text)
            logger.info("Message sent to Boss (scheduled)")
        except Exception as exc:
            logger.exception("Failed to send to Boss: %s", exc)
            self.activity.log_error("system", "send_to_boss", exc)

    async def startup_checks(self) -> bool:
        reload_settings()
        problems = validate_config()
        if problems:
            logger.error("Configuration problems: %s", problems)
            print("\n❌ Configuration error(s):")
            for p in problems:
                print(f"   • {p}")
            status = env_file_status()
            empty_keys = [k for k, v in status.items() if v == "empty" and not k.startswith("_")]
            if empty_keys:
                print(f"\n   Your {ENV_PATH} has keys but EMPTY values on disk.")
                print("   -> Save the file in your editor (Ctrl+S), then run again.")
            elif status.get("_file") == "missing":
                print(f"\n   Copy {ROOT_DIR / '.env.example'} to {ENV_PATH}")
            print()
            return False

        logger.info("Environment OK | Boss ID=%s", BOSS_TELEGRAM_ID)
        self._groq_ok = self.ai.connect()
        self._voice_ok = self.voice.connect()
        self.memory.list_all(limit=1)  # ensure DB loaded
        self.activity.log("system", "startup", "Aru AI v2 initialized")
        logger.info("SQLite ready at %s", self.memory.db_path)
        logger.info("Logging active at %s", LOGS_DIR / "aru.log")
        return True

    def _register_handlers(self) -> None:
        @self.client.on(events.NewMessage(incoming=True))
        async def on_incoming(event: events.NewMessage.Event) -> None:
            await self._handle_message(event, is_mention=False)

        @self.client.on(events.NewMessage(outgoing=True))
        async def on_outgoing(event: events.NewMessage.Event) -> None:
            # Only process outgoing private Saved Messages chat with self.
            if not event.is_private:
                return

            me = await self.client.get_me()
            if not me or event.chat_id != me.id:
                return

            await self._handle_message(event, is_mention=False, outgoing=True)

        @self.client.on(events.NewMessage(pattern=r"@\w+", incoming=True))
        async def on_mention(event: events.NewMessage.Event) -> None:
            me = await self.client.get_me()
            if me and me.username and f"@{me.username}".lower() in (event.raw_text or "").lower():
                await self._handle_message(event, is_mention=True)

    async def _handle_message(
        self,
        event: events.NewMessage.Event,
        *,
        is_mention: bool,
        outgoing: bool = False,
    ) -> None:
        try:
            if not event.is_private and not is_mention:
                return

            text = (event.raw_text or "").strip()
            is_voice = bool(event.message.voice or event.message.audio)

            if not text and not is_voice:
                return

            sender = await event.get_sender()
            authorized, sender_id = verify_sender(sender or event.sender_id)
            is_boss = authorized
            stripped = text.strip()
            lower = stripped.lower()
            command_detected = stripped.startswith("/")
            boss_only_command = any(
                lower.startswith(prefix)
                for prefix in (
                    "/research",
                    "/remember",
                    "/memories",
                    "/forget",
                    "/searchmemory",
                    "/task",
                    "/status",
                    "/unlock",
                    "/memory",
                    "/remind",
                )
            )

            logger.debug(
                "Telegram event | chat_id=%s sender_id=%s is_private=%s is_boss=%s command_detected=%s boss_only=%s out=%s boss_id=%s len=%s",
                event.chat_id,
                sender_id,
                event.is_private,
                is_boss,
                command_detected,
                boss_only_command,
                event.out,
                BOSS_TELEGRAM_ID,
                len(text),
            )

            logger.info(
                "Message received | chat=%s sender=%s mention=%s voice=%s is_private=%s out=%s len=%s",
                event.chat_id,
                sender_id,
                is_mention,
                is_voice,
                event.is_private,
                event.out,
                len(text),
            )

            if not authorized:
                await event.reply(unauthorized_message())
                logger.info(
                    "Unauthorized reply sent | sender=%s chat=%s is_boss=%s reply_generated=%s",
                    sender_id,
                    event.chat_id,
                    False,
                    True,
                )
                return

            if is_mention and event.is_private:
                return

            if is_voice:
                await self._handle_voice_message(event, event.chat_id)
                return

            response = await self._process_boss_message(event, text, event.chat_id)
            if response:
                await event.reply(response)
                logger.info(
                    "Message sent | chat=%s len=%s reply_generated=%s",
                    event.chat_id,
                    len(response),
                    True,
                )

        except FloodWaitError as exc:
            logger.warning("Flood wait %s seconds", exc.seconds)
            await asyncio.sleep(exc.seconds)
        except Exception as exc:
            logger.exception("Handler error: %s", exc)
            self.activity.log_error("system", "handler", exc)
            try:
                await event.reply(
                    "দুঃখিত বস, একটি ত্রুটি হয়েছে। আমি লগে রেকর্ড করেছি — একটু পরে আবার চেষ্টা করুন।"
                )
            except Exception:
                pass

    async def _handle_voice_message(
        self,
        event: events.NewMessage.Event,
        chat_id: int,
    ) -> None:
        """Download voice note, transcribe, and reply with AI response."""
        if not self._voice_ok:
            await event.reply("ভয়েস অ্যাসিস্ট্যান্ট এখন উপলব্ধ নয়। Groq API চেক করুন।")
            return

        try:
            audio_bytes = await event.message.download_media(bytes)
            if not audio_bytes:
                await event.reply("ভয়েস ফাইল ডাউনলোড করতে পারিনি।")
                return

            history = _chat_history[chat_id]
            transcript, reply = await self.voice.process_voice_message(
                audio_bytes,
                memory=self.memory,
                conversation_history=history,
            )

            if transcript:
                history.append({"role": "user", "content": f"[Voice] {transcript}"})
                history.append({"role": "assistant", "content": reply})
                if len(history) > MAX_HISTORY:
                    _chat_history[chat_id] = history[-MAX_HISTORY:]

                response = f"🎤 **Transcript:** {transcript}\n\n{reply}"
            else:
                response = reply

            await event.reply(response)
            logger.info("Voice response sent | chat=%s reply_generated=%s", chat_id, True)

        except Exception as exc:
            logger.exception("Voice handler error: %s", exc)
            self.activity.log_error("voice", "handle", exc)
            await event.reply(
                "ভয়েস প্রসেস করতে সমস্যা হয়েছে। আবার চেষ্টা করুন বা টেক্সটে লিখুন।"
            )

    async def _process_boss_message(
        self,
        event: events.NewMessage.Event,
        text: str,
        chat_id: int,
    ) -> str | None:
        """Route commands or forward to AI."""
        lower = text.lower()

        if lower.startswith("/unlock"):
            code = text.split(maxsplit=1)[1] if len(text.split()) > 1 else ""
            if verify_secret_code(code):
                return "সিক্রেট কোড যাচাই সফল ✅"
            return "ভুল সিক্রেট কোড।"

        research_result = await self.research.handle_command_async(
            text, memory=self.memory
        )
        if research_result is not None:
            return research_result

        for result in (
            handle_help_command(text),
            self.tasks.handle_command(text),
            self.memory.handle_v2_command(text),
            handle_memory_command(text, self.memory),
            handle_reminder_command(text, self.scheduler) if self.scheduler else None,
            handle_status_command(
                text,
                telegram_ok=self._telegram_ok,
                groq_ok=self._groq_ok,
                memory_count=len(self.memory.list_all(limit=500)),
                pending_tasks=self.tasks.pending_count(),
                voice_ok=self._voice_ok,
                activity_count=self.activity.count(),
            ),
        ):
            if result is not None:
                return result

        memory_ctx = self.memory.context_for_ai(text)
        history = _chat_history[chat_id]
        reply = await self.ai.generate(
            text,
            memory_context=memory_ctx,
            conversation_history=history,
        )

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        if len(history) > MAX_HISTORY:
            _chat_history[chat_id] = history[-MAX_HISTORY:]

        return reply

    async def run(self) -> None:
        if not await self.startup_checks():
            sys.exit(1)

        self._register_handlers()

        session_file = Path(str(SESSION_PATH) + ".session")
        if not session_file.exists():
            print(
                "\n📱 First-time Telegram login required.\n"
                "   Enter your phone number and login code when prompted below.\n"
            )

        if self._groq_ok:
            self._groq_ok = await self.ai.health_check()
            if self._groq_ok:
                logger.info("Groq health check passed (model=%s)", self.ai.active_model)

        logger.info("Starting Telegram client...")
        await self.client.connect()
        if not await self.client.is_user_authorized():
            print("Telegram: starting interactive login...")
            try:
                await self.client.start()
            except EOFError:
                logger.error("Telegram login requires interactive terminal (EOF)")
                print(
                    "\n❌ Telegram login needs an interactive terminal.\n"
                    "   Run in Cursor terminal:  python main.py\n"
                    "   Then enter your phone number and Telegram code.\n"
                )
                await self.client.disconnect()
                return

        self._telegram_ok = await self.client.is_user_authorized()
        if not self._telegram_ok:
            logger.error("Telegram login failed")
            print("❌ Telegram authorization failed. Run again and complete login.")
            return

        me = await self.client.get_me()
        logger.info("Login success as %s (id=%s)", me.username or me.first_name, me.id)

        self.scheduler = AruScheduler(
            self.send_to_boss,
            self.tasks,
            self.memory,
        )
        self.scheduler.start()

        print(BANNER)
        logger.info("Aru AI v2 is online and listening")

        try:
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown()
        await self.browser.stop()
        self.activity.log("system", "shutdown", "Aru AI v2 stopped")
        if self.client.is_connected():
            await self.client.disconnect()
        logger.info("Aru shutdown complete")


def main() -> None:
    bot = AruBot()
    try:
        asyncio.run(bot.run())
    except SessionPasswordNeededError:
        logger.error("2FA enabled — complete login in terminal when prompted")
        print("2FA required. Run `python main.py` in terminal and enter password.")
        sys.exit(1)
    except RPCError as exc:
        logger.exception("Telegram RPC error: %s", exc)
        sys.exit(1)
    except EOFError:
        logger.error("Interactive input required for Telegram login")
        print(
            "\n❌ Run `python main.py` in an interactive terminal "
            "to complete Telegram phone/code login.\n"
        )
        sys.exit(1)
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
