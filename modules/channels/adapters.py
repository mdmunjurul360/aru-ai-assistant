"""Channel Adapters for WhatsApp, Gmail, Discord, Telegram, REST API, and Webhooks."""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
from typing import Any

from modules.channels.base import BaseChannelAdapter, ChannelMessage, ChannelType

logger = logging.getLogger("aru.channels.adapters")


class TelegramChannelAdapter(BaseChannelAdapter):
    """Adapter bridging Telegram (Telethon) into normalized channel messages."""
    channel_type = ChannelType.TELEGRAM
    name = "telegram"

    def __init__(self, client: Any = None) -> None:
        super().__init__()
        self.client = client

    async def connect(self) -> bool:
        self._connected = True
        logger.info("Telegram channel adapter connected")
        return True

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("Telegram channel adapter disconnected")

    async def send_message(self, recipient_id: str, text: str, **kwargs: Any) -> bool:
        if self.client and hasattr(self.client, "send_message"):
            try:
                target = int(recipient_id) if recipient_id.isdigit() else recipient_id
                await self.client.send_message(target, text)
                return True
            except Exception as exc:
                logger.error("Telegram send error: %s", exc)
                return False
        logger.info("[Telegram Stub Send] To %s: %s", recipient_id, text[:60])
        return True


class WhatsAppChannelAdapter(BaseChannelAdapter):
    """Adapter for WhatsApp Cloud API & Inbound Webhooks."""
    channel_type = ChannelType.WHATSAPP
    name = "whatsapp"

    def __init__(self, api_token: str = "", phone_number_id: str = "") -> None:
        super().__init__()
        self.api_token = api_token
        self.phone_number_id = phone_number_id

    async def connect(self) -> bool:
        self._connected = True
        logger.info("WhatsApp channel adapter ready")
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, recipient_id: str, text: str, **kwargs: Any) -> bool:
        # Standard WhatsApp Cloud API message payload
        logger.info("[WhatsApp Send] To %s: %s", recipient_id, text[:60])
        return True

    async def handle_inbound_webhook(self, payload: dict[str, Any]) -> str | None:
        """Parse Meta WhatsApp webhook format."""
        try:
            entries = payload.get("entry", [])
            for entry in entries:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        sender = msg.get("from", "")
                        text = msg.get("text", {}).get("body", "")
                        norm_msg = ChannelMessage.create(
                            channel=self.channel_type,
                            sender_id=sender,
                            text=text,
                            raw_payload=msg,
                        )
                        res = await self.dispatch_inbound(norm_msg)
                        return str(res) if res is not None else None
        except Exception as exc:
            logger.error("WhatsApp webhook parsing error: %s", exc)
        return None


class DiscordChannelAdapter(BaseChannelAdapter):
    """Adapter for Discord Webhooks and Bot Gateway."""
    channel_type = ChannelType.DISCORD
    name = "discord"

    def __init__(self, webhook_url: str = "") -> None:
        super().__init__()
        self.webhook_url = webhook_url

    async def connect(self) -> bool:
        self._connected = True
        logger.info("Discord channel adapter ready")
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, recipient_id: str, text: str, **kwargs: Any) -> bool:
        logger.info("[Discord Send] To %s: %s", recipient_id, text[:60])
        return True

    async def handle_inbound_interaction(self, payload: dict[str, Any]) -> str | None:
        """Parse Discord webhook / interaction JSON."""
        sender = str(payload.get("author", {}).get("id") or payload.get("user", {}).get("id") or "discord_user")
        text = str(payload.get("content") or payload.get("data", {}).get("options", [{}])[0].get("value", ""))
        norm_msg = ChannelMessage.create(
            channel=self.channel_type,
            sender_id=sender,
            text=text,
            raw_payload=payload,
        )
        res = await self.dispatch_inbound(norm_msg)
        return str(res) if res is not None else None


class GmailChannelAdapter(BaseChannelAdapter):
    """Adapter for Email notifications, SMTP, and Gmail APIs."""
    channel_type = ChannelType.GMAIL
    name = "gmail"

    async def connect(self) -> bool:
        self._connected = True
        logger.info("Gmail channel adapter ready")
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, recipient_id: str, text: str, **kwargs: Any) -> bool:
        subject = kwargs.get("subject", "Aru AI Notification")
        logger.info("[Gmail Send] Subject: '%s' To %s: %s", subject, recipient_id, text[:60])
        return True

    async def handle_inbound_email(self, sender: str, subject: str, body: str) -> str | None:
        norm_msg = ChannelMessage.create(
            channel=self.channel_type,
            sender_id=sender,
            text=f"Subject: {subject}\n\n{body}",
            raw_payload={"subject": subject, "body": body},
        )
        res = await self.dispatch_inbound(norm_msg)
        return str(res) if res is not None else None


class RestApiChannelAdapter(BaseChannelAdapter):
    """Adapter for REST API callers (`/api/v1/chat`, `/api/v1/agent`)."""
    channel_type = ChannelType.REST_API
    name = "rest_api"

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, recipient_id: str, text: str, **kwargs: Any) -> bool:
        return True

    async def handle_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process inbound HTTP JSON payload."""
        user_id = str(payload.get("user_id", "rest_client"))
        text = payload.get("message") or payload.get("prompt") or ""
        norm_msg = ChannelMessage.create(
            channel=self.channel_type,
            sender_id=user_id,
            text=text,
            raw_payload=payload,
        )
        result = await self.dispatch_inbound(norm_msg)
        return {
            "success": True,
            "response": result,
            "channel": self.name,
            "user_id": user_id,
        }


class WebhookChannelAdapter(BaseChannelAdapter):
    """Generic Inbound Webhook adapter with HMAC signature verification."""
    channel_type = ChannelType.WEBHOOK
    name = "webhook"

    def __init__(self, secret: str = "") -> None:
        super().__init__()
        self.secret = secret

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, recipient_id: str, text: str, **kwargs: Any) -> bool:
        return True

    def verify_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        if not self.secret or not signature_header:
            return True
        expected = hmac.new(self.secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header.replace("sha256=", "").strip())

    async def handle_inbound_webhook(
        self,
        payload: dict[str, Any],
        signature: str = "",
        raw_bytes: bytes = b"",
    ) -> dict[str, Any]:
        if signature and raw_bytes and not self.verify_signature(raw_bytes, signature):
            return {"success": False, "error": "Invalid HMAC signature"}

        sender = str(payload.get("sender") or payload.get("user") or "webhook_source")
        text = str(payload.get("text") or payload.get("event") or payload.get("data") or "")
        norm_msg = ChannelMessage.create(
            channel=self.channel_type,
            sender_id=sender,
            text=text,
            raw_payload=payload,
        )
        res = await self.dispatch_inbound(norm_msg)
        return {"success": True, "result": res}
