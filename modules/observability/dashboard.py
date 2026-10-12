"""Observability Metrics Dashboard generator."""

from __future__ import annotations

import os
import time
from typing import Any

from modules.observability.telemetry import TelemetryCollector


class MetricsDashboard:
    """
    Renders structured metrics, telemetry analytics, and operational health summaries.
    """

    def __init__(self, collector: TelemetryCollector) -> None:
        self.collector = collector

    def get_system_metrics(self) -> dict[str, Any]:
        uptime_sec = time.time() - self.collector.start_time
        return {
            "uptime_sec": round(uptime_sec, 1),
            "uptime_human": f"{int(uptime_sec // 3600)}h {int((uptime_sec % 3600) // 60)}m {int(uptime_sec % 60)}s",
            "pid": os.getpid(),
        }

    def render_markdown(self) -> str:
        """Render markdown dashboard report."""
        sys_m = self.get_system_metrics()
        tokens = self.collector.get_token_summary()
        tools = self.collector.get_tool_analytics()

        lines = [
            "📊 **Aru AI OS — Observability Dashboard**\n",
            f"⏱️ **Uptime:** `{sys_m['uptime_human']}` (PID: `{sys_m['pid']}`)",
            f"💰 **Total Estimated Cost:** `${tokens['estimated_cost_usd']:.4f}`",
            f"🪙 **Tokens Consumed:** `{tokens['total_tokens']:,}` (Prompt: `{tokens['prompt_tokens']:,}` | Output: `{tokens['completion_tokens']:,}`)\n",
            "🛠️ **Tool Execution Analytics:**",
        ]

        if tools:
            for t in tools:
                lines.append(
                    f"• `{t['tool']}`: **{t['calls']}** calls | `{t['success_rate']}%` success | avg `{t['avg_duration_sec']}s`"
                )
        else:
            lines.append("• কোনো টুল ব্যবহারের রেকর্ড নেই (No executions recorded yet).")

        return "\n".join(lines)
