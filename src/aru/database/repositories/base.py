"""Base repository pattern implementation for ARU AI V4."""

from __future__ import annotations

import json
from typing import Any, Generic, TypeVar
import aiosqlite

from aru.database.connection import DatabaseManager

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Generic async repository providing database query and mutation primitives."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    @property
    def db(self) -> DatabaseManager:
        return self._db

    async def _fetch_one(
        self,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        """Execute a SELECT query and return a single row as a dictionary."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    async def _fetch_all(
        self,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        """Execute a SELECT query and return all rows as a list of dictionaries."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def _execute_insert(
        self,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> int:
        """Execute an INSERT statement and return the inserted rowid."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(query, params)
            return cursor.lastrowid or 0

    async def _execute_mutation(
        self,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> int:
        """Execute an UPDATE or DELETE statement and return rowcount."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(query, params)
            return cursor.rowcount or 0
