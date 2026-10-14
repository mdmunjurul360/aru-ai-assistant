"""Telemetry, Token Tracking, Cost Estimation, and Tool Analytics."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.config import DATABASE_PATH

logger = logging.getLogger("aru.observability.telemetry")

# Groq pricing per million tokens (approximate USD)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "qwen/qwen3.8-27b": {"input": 0.20, "output": 0.40},
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    "whisper-large-v3": {"input": 0.11, "output": 0.00},
}


@dataclass
class ToolUsageStats:
    """Aggregated invocation metrics for a tool."""
    tool_name: str
    calls: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_sec: float = 0.0

    @property
    def avg_duration_sec(self) -> float:
        return self.total_duration_sec / max(1, self.calls)

    @property
    def success_rate(self) -> float:
        return (self.successes / max(1, self.calls)) * 100.0


class TelemetryCollector:
    """
    Central telemetry collector tracking:
      - Prompt and completion tokens
      - API costs
      - Tool performance & failure rates
      - Agent trace execution latencies
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self.start_time = time.time()
        self._tool_stats: dict[str, ToolUsageStats] = {}
        self._tokens_by_model: dict[str, dict[str, int]] = {}
        self._total_cost_usd: float = 0.0
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
                CREATE TABLE IF NOT EXISTS telemetry_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_type TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    value_num REAL NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    timestamp TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def record_token_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Record tokens consumed and return estimated USD cost."""
        if model not in self._tokens_by_model:
            self._tokens_by_model[model] = {"prompt": 0, "completion": 0}

        self._tokens_by_model[model]["prompt"] += prompt_tokens
        self._tokens_by_model[model]["completion"] += completion_tokens

        pricing = MODEL_PRICING.get(model, {"input": 0.15, "output": 0.25})
        cost = (prompt_tokens / 1_000_000 * pricing["input"]) + (
            completion_tokens / 1_000_000 * pricing["output"]
        )
        self._total_cost_usd += cost

        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO telemetry_metrics (metric_type, key_name, value_num, metadata_json, timestamp)
                VALUES ('tokens', ?, ?, ?, ?);
                """,
                (model, prompt_tokens + completion_tokens, f'{{"cost": {cost}}}', now),
            )
            conn.commit()

        return cost

    def record_tool_execution(
        self,
        tool_name: str,
        duration_sec: float,
        success: bool,
    ) -> None:
        """Record performance statistics for a tool execution."""
        key = tool_name.strip().lower()
        if key not in self._tool_stats:
            self._tool_stats[key] = ToolUsageStats(tool_name=key)

        stat = self._tool_stats[key]
        stat.calls += 1
        if success:
            stat.successes += 1
        else:
            stat.failures += 1
        stat.total_duration_sec += duration_sec

    def get_token_summary(self) -> dict[str, Any]:
        total_prompt = sum(v["prompt"] for v in self._tokens_by_model.values())
        total_comp = sum(v["completion"] for v in self._tokens_by_model.values())
        return {
            "total_tokens": total_prompt + total_comp,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_comp,
            "estimated_cost_usd": round(self._total_cost_usd, 6),
            "by_model": self._tokens_by_model,
        }

    def get_tool_analytics(self) -> list[dict[str, Any]]:
        return [
            {
                "tool": s.tool_name,
                "calls": s.calls,
                "success_rate": round(s.success_rate, 1),
                "avg_duration_sec": round(s.avg_duration_sec, 3),
            }
            for s in sorted(self._tool_stats.values(), key=lambda x: x.calls, reverse=True)
        ]
