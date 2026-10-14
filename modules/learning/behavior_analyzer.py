"""Behavior pattern analysis and habit discovery."""

from __future__ import annotations

import collections
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modules.config import DATABASE_PATH

logger = logging.getLogger("aru.learning.behavior")


@dataclass
class BehaviorPattern:
    """A detected repeated user routine or pattern."""
    action_key: str
    frequency: int
    confidence: float
    description: str


class BehaviorAnalyzer:
    """
    Analyzes historical command invocations and activity log events
    to uncover recurring habits, repeated tasks, and common routines.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or DATABASE_PATH)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def analyze_patterns(self, min_frequency: int = 2) -> list[BehaviorPattern]:
        """Examine activity logs and conversation history for repeat behaviors."""
        patterns: list[BehaviorPattern] = []

        with self._get_connection() as conn:
            # Query recent activity log actions
            try:
                rows = conn.execute(
                    """
                    SELECT category, action, COUNT(*) as cnt
                    FROM activity_logs
                    GROUP BY category, action
                    HAVING cnt >= ?
                    ORDER BY cnt DESC;
                    """,
                    (min_frequency,),
                ).fetchall()

                for r in rows:
                    key = f"{r['category']}:{r['action']}"
                    freq = r["cnt"]
                    conf = min(0.99, 0.4 + 0.1 * freq)
                    patterns.append(
                        BehaviorPattern(
                            action_key=key,
                            frequency=freq,
                            confidence=round(conf, 2),
                            description=f"User frequently executes {r['category']} -> {r['action']} ({freq} times)",
                        )
                    )
            except Exception as exc:
                logger.warning("Activity log scan notice: %s", exc)

        return patterns
