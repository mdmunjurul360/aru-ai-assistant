"""Asynchronous SQLite connection manager for ARU AI V4."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Any
import aiosqlite

from aru.core.logging import StructuredLogger


class DatabaseManager:
    """
    Manages asynchronous SQLite connection lifecycle, WAL mode, pragmas,
    and connection pooling/safety for ARU AI V4.
    """

    def __init__(
        self,
        db_path: Path | str,
        logger: StructuredLogger | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._db_path = Path(db_path).resolve()
        self._logger = logger or StructuredLogger("aru.database")
        self._timeout = timeout
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    async def _apply_pragmas(self, conn: aiosqlite.Connection) -> None:
        """Apply performance and concurrency pragmas to SQLite connection."""
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA busy_timeout=5000;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")

    async def connect(self) -> aiosqlite.Connection:
        """Establish connection if not already open and apply WAL pragmas."""
        async with self._lock:
            if self._conn is None:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(str(self._db_path), timeout=self._timeout)
                conn.row_factory = aiosqlite.Row
                await self._apply_pragmas(conn)
                self._conn = conn
                self._logger.debug("Database connected: %s", self._db_path)
            return self._conn

    async def disconnect(self) -> None:
        """Close active connection cleanly."""
        async with self._lock:
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception as err:
                    self._logger.warning("Error closing database: %s", err)
                finally:
                    self._conn = None
                    self._logger.debug("Database disconnected: %s", self._db_path)

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """
        Transactional connection context manager.
        Commits on clean exit, rolls back on exception.
        """
        conn = await self.connect()
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def check_health(self) -> dict[str, Any]:
        """Verify database connectivity and return PRAGMA details."""
        async with self.get_connection() as conn:
            cursor = await conn.execute("PRAGMA journal_mode;")
            row = await cursor.fetchone()
            journal_mode = row[0] if row else "unknown"

            cursor = await conn.execute("SELECT 1;")
            await cursor.fetchone()

            return {
                "status": "healthy",
                "database_path": str(self._db_path),
                "journal_mode": str(journal_mode).upper(),
            }
