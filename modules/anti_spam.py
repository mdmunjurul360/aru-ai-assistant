"""Anti-spam auto-reply cooldown system for unauthorized users."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Iterator

from modules.config import DATABASE_DIR, DATABASE_PATH
from modules.db import get_db_connection

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger

logger = logging.getLogger("aru.anti_spam")

COOLDOWN_HOURS = 3
IGNORE_THRESHOLD = 100


@dataclass
class CooldownEntry:
    user_id: int
    last_reply_at: str
    message_count: int


class AntiSpamManager:
    """Track unauthorized user cooldowns and auto-reply frequency."""

    def __init__(
        self,
        db_path: str | None = None,
        activity: "ActivityLogger | None" = None,
    ) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self._activity = activity
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with get_db_connection(self.db_path) as conn:
            yield conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_cooldowns (
                    user_id INTEGER PRIMARY KEY,
                    last_reply_at TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cooldown_updated ON user_cooldowns(updated_at)"
            )
        logger.info("Anti-spam database ready at %s", self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _hours_ago(hours: int) -> str:
        dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        return dt.isoformat()

    def should_reply(self, user_id: int, is_boss: bool) -> tuple[bool, str]:
        """
        Check if we should reply to this user.
        Returns (should_reply, reason_code).
        reason_code: "boss" | "first_reply" | "cooldown_expired" | "cooldown_active" | "spam_threshold"
        """
        if is_boss:
            return True, "boss"

        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM user_cooldowns WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if not row:
            return True, "first_reply"

        last_reply = row["last_reply_at"]
        message_count = row["message_count"]
        cooldown_start = datetime.fromisoformat(last_reply)
        now = datetime.now(timezone.utc)
        elapsed = now - cooldown_start

        if elapsed >= timedelta(hours=COOLDOWN_HOURS):
            return True, "cooldown_expired"

        if message_count >= IGNORE_THRESHOLD:
            return False, "spam_threshold"

        return False, "cooldown_active"

    def record_reply(self, user_id: int, is_boss: bool) -> None:
        """Record that we replied to this user."""
        if is_boss:
            return

        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO user_cooldowns (user_id, last_reply_at, message_count, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    last_reply_at = ?,
                    message_count = 0,
                    updated_at = ?
                """,
                (user_id, now, now, now, now, now),
            )

        if self._activity:
            self._activity.log(
                "system",
                "AUTO_REPLY_SENT",
                f"user_id={user_id} cooldown_until={self._hours_until_next_reply(user_id)}h",
            )
        logger.info("Auto-reply sent to user %s, cooldown active", user_id)

    def record_ignored_message(self, user_id: int) -> None:
        """Record an ignored message from user in cooldown."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT message_count FROM user_cooldowns WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            new_count = (row["message_count"] if row else 0) + 1

            if not row:
                now = self._now()
                conn.execute(
                    """
                    INSERT INTO user_cooldowns (user_id, last_reply_at, message_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, now, new_count, now, now),
                )
            else:
                conn.execute(
                    "UPDATE user_cooldowns SET message_count = ?, updated_at = ? WHERE user_id = ?",
                    (new_count, self._now(), user_id),
                )

        action = (
            "COOLDOWN_ACTIVE"
            if new_count < IGNORE_THRESHOLD
            else "SPAM_THRESHOLD_REACHED"
        )
        if self._activity:
            self._activity.log(
                "system",
                action,
                f"user_id={user_id} message_count={new_count}/{IGNORE_THRESHOLD}",
            )
        logger.warning(
            "Ignored message from user %s (cooldown) count=%s/%s",
            user_id,
            new_count,
            IGNORE_THRESHOLD,
        )

    def _hours_until_next_reply(self, user_id: int) -> int:
        """Calculate hours remaining in cooldown."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_reply_at FROM user_cooldowns WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if not row:
            return 0

        last_reply = datetime.fromisoformat(row["last_reply_at"])
        cooldown_end = last_reply + timedelta(hours=COOLDOWN_HOURS)
        now = datetime.now(timezone.utc)
        remaining = cooldown_end - now

        return max(0, int(remaining.total_seconds() / 3600) + (1 if remaining.total_seconds() % 3600 else 0))

    def get_cooldown_info(self, user_id: int) -> CooldownEntry | None:
        """Get cooldown status for a user."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM user_cooldowns WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if not row:
            return None

        return CooldownEntry(
            user_id=user_id,
            last_reply_at=row["last_reply_at"],
            message_count=row["message_count"],
        )

    def clear_cooldown(self, user_id: int) -> None:
        """Manually clear cooldown for a user (admin only)."""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM user_cooldowns WHERE user_id = ?",
                (user_id,),
            )
        if self._activity:
            self._activity.log("system", "COOLDOWN_CLEARED", f"user_id={user_id}")
        logger.info("Cooldown cleared for user %s", user_id)
