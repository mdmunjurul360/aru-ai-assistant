"""Habit tracking engine with streaks and frequency monitoring."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any

from modules.config import DATABASE_PATH

logger = logging.getLogger("aru.scheduling.habits")


@dataclass
class HabitItem:
    """User habit entity."""
    habit_id: int
    name: str
    target_frequency: str  # "daily", "weekly"
    current_streak: int
    best_streak: int
    last_completed_at: str | None
    created_at: str


class HabitStore:
    """SQLite-backed tracker for daily and weekly recurring habits."""

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
                CREATE TABLE IF NOT EXISTS user_habits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    target_frequency TEXT DEFAULT 'daily',
                    current_streak INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    last_completed_at TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def add_habit(self, name: str, target_frequency: str = "daily") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO user_habits (name, target_frequency, current_streak, best_streak, created_at)
                VALUES (?, ?, 0, 0, ?)
                ON CONFLICT(name) DO NOTHING;
                """,
                (name.strip(), target_frequency, now),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def complete_habit(self, name: str) -> dict[str, Any]:
        """Record habit completion and update streak logic."""
        now = datetime.now(timezone.utc)
        today_str = now.date().isoformat()

        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT id, current_streak, best_streak, last_completed_at FROM user_habits WHERE name = ?;",
                (name.strip(),),
            ).fetchone()

            if not row:
                self.add_habit(name)
                row = conn.execute(
                    "SELECT id, current_streak, best_streak, last_completed_at FROM user_habits WHERE name = ?;",
                    (name.strip(),),
                ).fetchone()

            last_dt_str = row["last_completed_at"]
            current_streak = row["current_streak"]
            best_streak = row["best_streak"]

            if last_dt_str:
                last_date = datetime.fromisoformat(last_dt_str).date()
                days_diff = (now.date() - last_date).days
                if days_diff == 0:
                    # Already completed today
                    return {"name": name, "streak": current_streak, "already_completed": True}
                elif days_diff == 1:
                    current_streak += 1
                else:
                    current_streak = 1
            else:
                current_streak = 1

            best_streak = max(best_streak, current_streak)

            conn.execute(
                """
                UPDATE user_habits
                SET current_streak = ?, best_streak = ?, last_completed_at = ?
                WHERE id = ?;
                """,
                (current_streak, best_streak, now.isoformat(), row["id"]),
            )
            conn.commit()

        return {
            "name": name,
            "streak": current_streak,
            "best_streak": best_streak,
            "already_completed": False,
        }

    def list_habits(self) -> list[HabitItem]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, name, target_frequency, current_streak, best_streak, last_completed_at, created_at FROM user_habits ORDER BY current_streak DESC;"
            ).fetchall()
            return [
                HabitItem(
                    habit_id=r["id"],
                    name=r["name"],
                    target_frequency=r["target_frequency"],
                    current_streak=r["current_streak"],
                    best_streak=r["best_streak"],
                    last_completed_at=r["last_completed_at"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
