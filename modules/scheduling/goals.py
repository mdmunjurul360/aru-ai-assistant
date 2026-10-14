"""Long-term goals and milestone tracker."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.config import DATABASE_PATH

logger = logging.getLogger("aru.scheduling.goals")


@dataclass
class GoalItem:
    """User goal with measurable progress and milestone list."""
    goal_id: int
    title: str
    description: str
    target_date: str | None
    milestones: list[dict[str, Any]]
    progress_pct: int
    status: str  # "active", "completed", "paused"
    created_at: str


class GoalStore:
    """SQLite-backed goal management and milestone evaluation store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self._ensure_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _ensure_table(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    target_date TEXT,
                    milestones_json TEXT DEFAULT '[]',
                    progress_pct INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def add_goal(
        self,
        title: str,
        description: str = "",
        target_date: str | None = None,
        milestones: list[str] | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        ms_list = [{"title": m, "done": False} for m in (milestones or [])]
        ms_str = json.dumps(ms_list, ensure_ascii=False)

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO user_goals (title, description, target_date, milestones_json, progress_pct, status, created_at)
                VALUES (?, ?, ?, ?, 0, 'active', ?);
                """,
                (title.strip(), description.strip(), target_date, ms_str, now),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def update_progress(self, goal_id: int, progress_pct: int) -> bool:
        new_pct = max(0, min(100, progress_pct))
        status = "completed" if new_pct >= 100 else "active"

        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE user_goals SET progress_pct = ?, status = ? WHERE id = ?;",
                (new_pct, status, goal_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_goals(self, status: str = "active") -> list[GoalItem]:
        with self._get_connection() as conn:
            if status == "all":
                rows = conn.execute("SELECT * FROM user_goals ORDER BY progress_pct DESC;").fetchall()
            else:
                rows = conn.execute("SELECT * FROM user_goals WHERE status = ? ORDER BY progress_pct DESC;", (status,)).fetchall()

            return [
                GoalItem(
                    goal_id=r["id"],
                    title=r["title"],
                    description=r["description"],
                    target_date=r["target_date"],
                    milestones=json.loads(r["milestones_json"] or "[]"),
                    progress_pct=r["progress_pct"],
                    status=r["status"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
