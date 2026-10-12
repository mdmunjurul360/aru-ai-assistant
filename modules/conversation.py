"""Persistent SQLite conversation history store for multi-turn AI context."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from modules.config import DATABASE_PATH
from modules.db import get_db_connection

logger = logging.getLogger("aru.conversation")


@dataclass
class ConversationMessage:
    id: int
    chat_id: int
    role: str
    message: str
    created_at: str


class ConversationHistoryStore:
    """Store and retrieve multi-turn conversation messages per chat."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self._init_db()

    def _conn(self) -> Iterator[sqlite3.Connection]:
        return get_db_connection(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_chat_created ON conversation_history(chat_id, created_at)"
            )
        logger.debug("Conversation history table ready at %s", self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def add_message(self, chat_id: int, role: str, message: str) -> ConversationMessage:
        """Record a single message in the persistent history."""
        now = self._now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO conversation_history (chat_id, role, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, role.strip(), message.strip(), now),
            )
            msg_id = cur.lastrowid
            row = conn.execute("SELECT * FROM conversation_history WHERE id = ?", (msg_id,)).fetchone()
        assert row is not None
        return ConversationMessage(
            id=row["id"],
            chat_id=row["chat_id"],
            role=row["role"],
            message=row["message"],
            created_at=row["created_at"],
        )

    def get_history(self, chat_id: int, *, limit: int = 20) -> list[dict[str, str]]:
        """
        Retrieve latest messages for chat_id formatted for Groq/OpenAI chat completions.
        Returns chronologically sorted list: [{'role': 'user', 'content': '...'}, ...]
        """
        with self._conn() as conn:
            # Fetch latest limit rows in descending order, then reverse to chronological
            rows = conn.execute(
                """
                SELECT role, message FROM conversation_history
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()

        # Reverse to chronological order (oldest to newest among the latest N)
        return [{"role": r["role"], "content": r["message"]} for r in reversed(rows)]

    def clear_history(self, chat_id: int) -> int:
        """Clear all conversation history for a specific chat."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM conversation_history WHERE chat_id = ?",
                (chat_id,),
            )
        deleted = cur.rowcount
        logger.info("Cleared %d messages for chat_id=%s", deleted, chat_id)
        return deleted

    def prune_history(self, chat_id: int, keep_last: int = 60) -> int:
        """Prune older conversation records beyond keep_last to prevent database bloating."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                DELETE FROM conversation_history
                WHERE chat_id = ? AND id NOT IN (
                    SELECT id FROM conversation_history
                    WHERE chat_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (chat_id, chat_id, keep_last),
            )
            pruned = cur.rowcount
        if pruned > 0:
            logger.debug("Pruned %d older messages for chat_id=%s (retained %d)", pruned, chat_id, keep_last)
        return pruned

    def get_trimmed_history(
        self,
        chat_id: int,
        *,
        limit: int = 10,
        max_chars_per_turn: int = 500,
    ) -> list[dict[str, str]]:
        """
        Retrieve recent turns trimmed to avoid token explosion.
        Older verbose turns are truncated while keeping the most recent turn intact.
        """
        raw = self.get_history(chat_id, limit=limit)
        if not raw:
            return []

        trimmed: list[dict[str, str]] = []
        for idx, msg in enumerate(raw):
            role = msg["role"]
            content = msg["content"]
            # Only truncate if not the immediate last turn and text exceeds threshold
            if idx < len(raw) - 1 and len(content) > max_chars_per_turn:
                content = content[:max_chars_per_turn] + " ... [trimmed for brevity]"
            trimmed.append({"role": role, "content": content})

        return trimmed

    def count(self, chat_id: int | None = None) -> int:
        """Count messages stored for a specific chat or overall."""
        with self._conn() as conn:
            if chat_id is not None:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM conversation_history WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM conversation_history").fetchone()
        return int(row["c"]) if row else 0

    def count_messages(self, chat_id: int | None = None) -> int:
        """Alias for count()."""
        return self.count(chat_id)
