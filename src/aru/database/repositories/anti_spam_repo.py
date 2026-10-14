"""Anti-spam repository for ARU AI V4."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from aru.database.repositories.base import BaseRepository


class AntiSpamRepository(BaseRepository[dict[str, Any]]):
    """Manages rate-limit cooldowns, security incident events, and authorized whitelists."""

    async def set_cooldown(
        self,
        user_id: int,
        cooldown_until: datetime | str,
        reason: str = "",
        warning_count: int = 1,
    ) -> None:
        """Set or update user cooldown timestamp."""
        until_str = (
            cooldown_until.isoformat()
            if isinstance(cooldown_until, datetime)
            else str(cooldown_until)
        )
        await self._execute_insert(
            """
            INSERT INTO anti_spam_cooldowns (user_id, cooldown_until, reason, warning_count, last_message_time)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                cooldown_until = excluded.cooldown_until,
                reason = excluded.reason,
                warning_count = anti_spam_cooldowns.warning_count + 1,
                last_message_time = CURRENT_TIMESTAMP;
            """,
            (user_id, until_str, reason, warning_count),
        )

    async def get_cooldown(self, user_id: int) -> dict[str, Any] | None:
        """Get cooldown record for user."""
        return await self._fetch_one(
            "SELECT * FROM anti_spam_cooldowns WHERE user_id = ?;",
            (user_id,),
        )

    async def is_cooled_down(self, user_id: int) -> bool:
        """Check whether user currently has an active cooldown in effect."""
        row = await self.get_cooldown(user_id)
        if not row:
            return False

        until_val = row["cooldown_until"]
        if isinstance(until_val, str):
            try:
                dt_until = datetime.fromisoformat(until_val)
                if dt_until.tzinfo is None:
                    dt_until = dt_until.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                return now < dt_until
            except Exception:
                pass
        return True

    async def clear_cooldown(self, user_id: int) -> bool:
        """Remove cooldown for a user."""
        count = await self._execute_mutation(
            "DELETE FROM anti_spam_cooldowns WHERE user_id = ?;",
            (user_id,),
        )
        return count > 0

    async def record_spam_event(
        self,
        user_id: int,
        event_type: str,
        details: str = "",
    ) -> int:
        """Record a security or spam event for audit logging."""
        return await self._execute_insert(
            """
            INSERT INTO anti_spam_events (user_id, event_type, details)
            VALUES (?, ?, ?);
            """,
            (user_id, event_type, details),
        )

    async def add_to_whitelist(self, user_id: int, notes: str = "") -> bool:
        """Add user to whitelist."""
        await self._execute_insert(
            """
            INSERT INTO anti_spam_whitelist (user_id, notes)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET notes = excluded.notes;
            """,
            (user_id, notes),
        )
        return True

    async def is_whitelisted(self, user_id: int) -> bool:
        """Check whether user is whitelisted."""
        row = await self._fetch_one(
            "SELECT 1 FROM anti_spam_whitelist WHERE user_id = ?;",
            (user_id,),
        )
        return row is not None

    async def remove_from_whitelist(self, user_id: int) -> bool:
        """Remove user from whitelist."""
        count = await self._execute_mutation(
            "DELETE FROM anti_spam_whitelist WHERE user_id = ?;",
            (user_id,),
        )
        return count > 0
