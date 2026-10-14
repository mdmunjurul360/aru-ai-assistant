"""Conversation repository for ARU AI V4."""

from __future__ import annotations

import json
from typing import Any
from aru.database.repositories.base import BaseRepository


class ConversationRepository(BaseRepository[dict[str, Any]]):
    """Manages persistence and retrieval of chat conversation history."""

    async def add_message(
        self,
        session_id: str,
        user_id: int,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Add a conversation message to history and return inserted ID."""
        meta_json = json.dumps(metadata) if metadata else None
        return await self._execute_insert(
            """
            INSERT INTO conversations (session_id, user_id, role, content, metadata)
            VALUES (?, ?, ?, ?, ?);
            """,
            (session_id, user_id, role, content, meta_json),
        )

    async def get_history(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Retrieve recent conversation history for a session in chronological order."""
        # Query newest messages up to limit, then reverse to chronological order
        rows = await self._fetch_all(
            """
            SELECT id, session_id, user_id, role, content, metadata, created_at
            FROM conversations
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?;
            """,
            (session_id, limit),
        )
        for r in rows:
            if r.get("metadata"):
                try:
                    r["metadata"] = json.loads(r["metadata"])
                except Exception:
                    pass
        return list(reversed(rows))

    async def clear_history(self, session_id: str) -> int:
        """Remove all messages for a session."""
        return await self._execute_mutation(
            "DELETE FROM conversations WHERE session_id = ?;",
            (session_id,),
        )

    async def count(self, session_id: str | None = None) -> int:
        """Count total stored messages."""
        if session_id:
            row = await self._fetch_one(
                "SELECT COUNT(*) as cnt FROM conversations WHERE session_id = ?;",
                (session_id,),
            )
        else:
            row = await self._fetch_one("SELECT COUNT(*) as cnt FROM conversations;")
        return row["cnt"] if row else 0
