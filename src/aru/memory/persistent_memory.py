"""Persistent episodic memory store implementation for ARU AI V4."""

from __future__ import annotations

from aru.database.repositories.memory_repo import MemoryRepository
from aru.memory.interfaces import IPersistentMemory
from aru.memory.models import MemoryFact


class PersistentMemory(IPersistentMemory):
    """
    Database-backed episodic memory with full-text search (FTS5)
    and categorical retrieval.
    """

    def __init__(self, memory_repo: MemoryRepository) -> None:
        self._repo = memory_repo

    def _row_to_fact(self, row: dict) -> MemoryFact:
        """Convert repository dictionary row to MemoryFact domain model."""
        tags_raw = row.get("tags") or ""
        tags_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
        return MemoryFact(
            id=row.get("id"),
            key=row.get("key"),
            content=row.get("content", ""),
            category=row.get("category", "general"),
            tags=tags_list,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    async def store_fact(
        self,
        content: str,
        key: str | None = None,
        category: str = "general",
        tags: list[str] | None = None,
    ) -> int:
        """Persist or update an episodic fact."""
        tags_str = ",".join(tags) if tags else None
        return await self._repo.store(
            content=content,
            key=key,
            category=category,
            tags=tags_str,
        )

    async def get_fact(self, key: str) -> MemoryFact | None:
        """Retrieve memory fact by key."""
        row = await self._repo.get_by_key(key)
        return self._row_to_fact(row) if row else None

    async def search_facts(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[MemoryFact]:
        """Search memories via full-text search matching."""
        rows = await self._repo.search(query_text=query, category=category, limit=limit)
        return [self._row_to_fact(r) for r in rows]

    async def delete_fact(self, key: str) -> bool:
        """Delete memory fact by key."""
        return await self._repo.delete_by_key(key)

    async def list_facts(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[MemoryFact]:
        """List stored facts optionally filtered by category."""
        if category:
            rows = await self._repo.list_by_category(category, limit=limit)
        else:
            rows = await self._repo.search("", limit=limit)
            if not rows:
                # If query empty returns empty in search, list directly from table
                rows = await self._repo._fetch_all(
                    "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?;",
                    (limit,),
                )
        return [self._row_to_fact(r) for r in rows]
