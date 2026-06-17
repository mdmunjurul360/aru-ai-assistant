"""Boss-only authentication for incoming Telegram messages."""

from __future__ import annotations

import logging

from modules.config import BOSS_TELEGRAM_ID, SECRET_CODE, UNAUTHORIZED_REPLY

logger = logging.getLogger("aru.auth")


def get_sender_id(sender) -> int | None:
    """Extract numeric Telegram user ID from a Telethon sender entity or numeric id."""
    if sender is None:
        return None
    if isinstance(sender, int):
        return sender
    return getattr(sender, "id", None) or getattr(sender, "sender_id", None)


def is_boss(sender_id: int | None) -> bool:
    """Return True if sender is the configured Boss."""
    if sender_id is None or not BOSS_TELEGRAM_ID:
        return False
    return int(sender_id) == int(BOSS_TELEGRAM_ID)


def verify_sender(sender) -> tuple[bool, int | None]:
    """
    Verify incoming message sender.
    Returns (authorized, sender_id).
    """
    sender_id = get_sender_id(sender)
    logger.debug(
        "Verifying sender_id=%s against BOSS_TELEGRAM_ID=%s",
        sender_id,
        BOSS_TELEGRAM_ID,
    )
    authorized = is_boss(sender_id)
    if authorized:
        logger.debug("Boss verified: %s", sender_id)
    else:
        logger.warning("Unauthorized access attempt from: %s", sender_id)
    return authorized, sender_id


def unauthorized_message() -> str:
    return UNAUTHORIZED_REPLY


def verify_secret_code(code: str) -> bool:
    """Optional secret code check (e.g. /unlock)."""
    if not SECRET_CODE:
        return False
    return code.strip() == SECRET_CODE.strip()
