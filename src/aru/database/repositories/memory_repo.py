"""Memory repository for ARU AI V4 with FTS5 search."""

from __future__ import annotations

from typing import Any
from aru.database.repositories.base import BaseRepository


class MemoryRepository(BaseRepository[dict[str, Any]]):
    """Manages long-term episodic memories and full-text search index."""

    async def store(
        self,
        content: str,
        key: str | None = None,
        category: str = "general",
        tags: str | None = None,
    ) -> int:
        """Store or update a memory item and return row ID."""
        if key:
            # Upsert on key conflict
            query = """
            INSERT INTO memories (key, content, category, tags, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                content = excluded.content,
                category = excluded.category,
                tags = excluded.tags,
                updated_at = CURRENT_TIMESTAMP;
            """
            return await self._execute_insert(query, (key, content, category, tags))
        else:
            query = """
            INSERT INTO memories (key, content, category, tags)
            VALUES (?, ?, ?, ?);
            """
            return await self._execute_insert(query, (None, content, category, tags))

    async def get_by_id(self, memory_id: int) -> dict[str, Any] | None:
        """Retrieve memory by its numeric primary key."""
        return await self._fetch_one(
            "SELECT * FROM memories WHERE id = ?;",
            (memory_id,),
        )

    async def get_by_key(self, key: str) -> dict[str, Any] | None:
        """Retrieve memory by its unique natural key."""
        return await self._fetch_one(
            "SELECT * FROM memories WHERE key = ?;",
            (key,),
        )

    async def search(
        self,
        query_text: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories using FTS5 full-text match with fallback to LIKE search."""
        clean_query = query_text.strip().replace("'", "").replace('"', "")
        if not clean_query:
            return []

        # Try FTS5 MATCH first
        try:
            fts_term = f'"{clean_query}"*'
            if category:
                sql = """
                SELECT m.* FROM memories m
                JOIN memories_fts f ON m.id = f.rowid
                WHERE memories_fts MATCH ? AND m.category = ?
                ORDER BY rank
                LIMIT ?;
                """
                results = await self._fetch_all(sql, (fts_term, category, limit))
            else:
                sql = """
                SELECT m.* FROM memories m
                JOIN memories_fts f ON m.id = f.rowid
                WHERE memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?;
                """
                results = await self._fetch_all(sql, (fts_term, limit))

            if results:
                return results
        except Exception:
            # Fallback to standard LIKE if FTS expression fails
            pass

        # Fallback to LIKE search
        like_pattern = f"%{clean_query}%"
        if category:
            sql = """
            SELECT * FROM memories
            WHERE (content LIKE ? OR key LIKE ? OR tags LIKE ?) AND category = ?
            ORDER BY updated_at DESC
            LIMIT ?;
            """
            return await self._fetch_all(sql, (like_pattern, like_pattern, like_pattern, category, limit))
        else:
            sql = """
            SELECT * FROM memories
            WHERE content LIKE ? OR key LIKE ? OR tags LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?;
            """
            return await self._fetch_all(sql, (like_pattern, like_pattern, like_pattern, limit))

    async def list_by_category(
        self,
        category: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List memories belonging to a specific category."""
        return await self._fetch_all(
            "SELECT * FROM memories WHERE category = ? ORDER BY updated_at DESC LIMIT ?;",
            (category, limit),
        )

    async def delete(self, memory_id: int) -> bool:
        """Delete memory by numeric ID."""
        count = await self._execute_mutation("DELETE FROM memories WHERE id = ?;", (memory_id,))
        return count > 0

    async def delete_by_key(self, key: str) -> bool:
        """Delete memory by unique key."""
        count = await self._execute_mutation("DELETE FROM memories WHERE key = ?;", (key,))
        return count > 0

    async def count(self) -> int:
        """Return total memory count."""
        row = await self._fetch_one("SELECT COUNT(*) as cnt FROM memories;")
        return row["cnt"] if row else 0
