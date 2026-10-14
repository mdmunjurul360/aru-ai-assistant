"""Database schema migration runner for ARU AI V4."""

from __future__ import annotations

from pathlib import Path
from aru.database.connection import DatabaseManager
from aru.core.logging import StructuredLogger


class MigrationRunner:
    """Executes version-controlled SQL migrations sequentially and idempotently."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        migrations_dir: Path | str | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._db = db_manager
        self._dir = Path(migrations_dir) if migrations_dir else Path(__file__).resolve().parent
        self._logger = logger or StructuredLogger("aru.database.migrations")

    async def run(self) -> list[str]:
        """Run all pending SQL migrations in ascending order."""
        applied_now: list[str] = []

        async with self._db.get_connection() as conn:
            # 1. Ensure migrations tracking table exists
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _v4_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 2. Query already applied migrations
            cursor = await conn.execute("SELECT name FROM _v4_migrations;")
            rows = await cursor.fetchall()
            already_applied = {row[0] for row in rows}

            # 3. Discover SQL migration files
            migration_files = sorted(self._dir.glob("*.sql"))

            for file_path in migration_files:
                name = file_path.name
                if name in already_applied:
                    continue

                self._logger.info("Applying migration: %s", name)
                sql_content = file_path.read_text(encoding="utf-8")

                await conn.executescript(sql_content)
                await conn.execute(
                    "INSERT INTO _v4_migrations (name) VALUES (?);",
                    (name,),
                )
                applied_now.append(name)
                self._logger.info("Successfully applied migration: %s", name)

        return applied_now
