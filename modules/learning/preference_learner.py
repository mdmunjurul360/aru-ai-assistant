"""Autonomous User Preference Learning and Profile Store."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.config import DATABASE_PATH

logger = logging.getLogger("aru.learning.preferences")


@dataclass
class UserPreference:
    """A learned user preference."""
    key: str
    category: str
    value: str
    confidence: float
    last_updated: str
    source_sample: str


class PreferenceLearner:
    """
    Extracts and manages persistent user preferences.
    Detects language preferences, communication styles, technical affinities,
    and lifestyle/schedule traits from user messages.
    """

    EXPLICIT_PATTERNS = [
        # Language preference
        (r"(?:always\s+reply\s+in|speak\s+in|use\s+language)\s+(bangla|bengali|english|banglish)", "language", "language"),
        # Form of address
        (r"(?:call\s+me|my\s+name\s+is)\s+([A-Za-z0-9_\u0980-\u09FF]+)", "identity", "preferred_name"),
        # Response style
        (r"(?:be\s+more|give\s+me|prefer)\s+(concise|detailed|short|technical|bulleted|formal)\s+(?:answers|replies)?", "style", "response_verbosity"),
        # Code/tech preference
        (r"(?:prefer|always\s+use)\s+(python|typescript|docker|playwright|sqlite|fastapi)", "tech", "tech_stack"),
        # Timezone / schedule
        (r"(?:my\s+timezone\s+is|i\s+live\s+in)\s+([A-Za-z0-9_/]+)", "schedule", "timezone"),
    ]

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
                CREATE TABLE IF NOT EXISTS user_preference_profile (
                    key TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    last_updated TEXT NOT NULL,
                    source_sample TEXT
                );
                """
            )
            conn.commit()

    def learn_from_message(self, message: str) -> list[UserPreference]:
        """Inspect a message turn and update learned preferences."""
        if not message or not message.strip():
            return []

        learned: list[UserPreference] = []
        lower = message.lower().strip()

        for pattern, cat, key in self.EXPLICIT_PATTERNS:
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                val = match.group(1).strip()
                pref = self.set_preference(key=key, category=cat, value=val, confidence=0.95, sample=message)
                learned.append(pref)

        return learned

    def set_preference(
        self,
        key: str,
        category: str,
        value: str,
        confidence: float = 1.0,
        sample: str = "",
    ) -> UserPreference:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO user_preference_profile (key, category, value, confidence, last_updated, source_sample)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    last_updated = excluded.last_updated,
                    source_sample = excluded.source_sample;
                """,
                (key, category, value, confidence, now, sample),
            )
            conn.commit()

        logger.info("Learned user preference: [%s] %s = %s", category, key, value)
        return UserPreference(
            key=key,
            category=category,
            value=value,
            confidence=confidence,
            last_updated=now,
            source_sample=sample,
        )

    def get_preference(self, key: str) -> str | None:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM user_preference_profile WHERE key = ?;", (key,)
            ).fetchone()
            return row["value"] if row else None

    def get_all_preferences(self) -> dict[str, str]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT key, value FROM user_preference_profile;"
            ).fetchall()
            return {r["key"]: r["value"] for r in rows}

    def format_profile(self) -> str:
        prefs = self.get_all_preferences()
        if not prefs:
            return "No learned user preferences yet."
        lines = ["👤 **Learned User Profile:**"]
        for k, v in prefs.items():
            lines.append(f"• `{k}`: **{v}**")
        return "\n".join(lines)
