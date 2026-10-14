"""Scheduling intelligence: Daily briefing, Weekly review, and Auto follow-up commitment detector."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from modules.scheduling.goals import GoalStore
from modules.scheduling.habits import HabitStore
from modules.tasks import TaskManager

logger = logging.getLogger("aru.scheduling.intelligence")


class SchedulingIntelligence:
    """
    Intelligent scheduling assistant synthesizing:
      - Daily briefings
      - Weekly reviews
      - Conversational commitment detection & auto follow-ups
    """

    COMMITMENT_PATTERNS = [
        (r"(?:i\s+will|i'll|i\s+plan\s+to|i\s+need\s+to|i\s+must)\s+([a-zA-Z0-9_\s]{5,60})\s+(?:by|before|tomorrow|next\s+week|on\s+monday|tonight)", "commitment"),
        (r"(?:remind\s+me\s+to|don't\s+forget\s+to)\s+([a-zA-Z0-9_\s]{5,60})", "explicit_reminder"),
        (r"(?:follow\s+up\s+with|check\s+with)\s+([a-zA-Z0-9_\s]{3,30})", "follow_up"),
    ]

    def __init__(
        self,
        task_manager: TaskManager | None = None,
        habit_store: HabitStore | None = None,
        goal_store: GoalStore | None = None,
    ) -> None:
        self.tasks = task_manager
        self.habits = habit_store or HabitStore()
        self.goals = goal_store or GoalStore()

    def generate_daily_briefing(self) -> str:
        """Construct comprehensive executive daily briefing."""
        now = datetime.now()
        date_str = now.strftime("%A, %d %B %Y")

        pending_tasks = self.tasks.list_pending(limit=5) if self.tasks else []
        active_habits = self.habits.list_habits()
        active_goals = self.goals.list_goals(status="active")

        lines = [
            f"🌅 **Executive Daily Briefing — Aru AI OS**",
            f"📅 {date_str}\n",
            "📋 **আজকের গুরুত্বপূর্ণ টাস্কসমূহ:**",
        ]

        if pending_tasks:
            for t in pending_tasks:
                lines.append(f"• [ID #{t.id}] **{t.title}** (Priority: `{t.priority}`)")
        else:
            lines.append("• কোনো পেন্ডিং টাস্ক নেই। দুর্দান্ত!")

        lines.append("\n🔥 **দৈনিক অভ্যাস ও স্ট্রাইক (Habits):**")
        if active_habits:
            for h in active_habits:
                lines.append(f"• {h.name} — `{h.current_streak} days streak` 🔥")
        else:
            lines.append("• কোনো সক্রিয় অভ্যাস ট্র্যাক করা নেই।")

        lines.append("\n🎯 **চলমান মূল লক্ষ্য (Goals):**")
        if active_goals:
            for g in active_goals:
                lines.append(f"• **{g.title}** ({g.progress_pct}% সম্পন্ন)")
        else:
            lines.append("• কোনো সক্রিয় লক্ষ্য নেই।")

        lines.append("\nআজকের দিনটি উৎপাদনশীল হোক, বস! 🚀")
        return "\n".join(lines)

    def generate_weekly_review(self) -> str:
        """Construct comprehensive weekly productivity review."""
        active_goals = self.goals.list_goals(status="active")
        habits = self.habits.list_habits()
        all_tasks = self.tasks.list_all(limit=50) if self.tasks else []

        completed_tasks = [t for t in all_tasks if getattr(t, "status", "") == "done"]
        total_tasks = len(all_tasks)
        completion_rate = int((len(completed_tasks) / max(1, total_tasks)) * 100)

        lines = [
            "📊 **সাপ্তাহিক পর্যালোচনা (Weekly Executive Review) — Aru AI OS**\n",
            f"• সম্পন্ন টাস্ক: **{len(completed_tasks)}** / {total_tasks} ({completion_rate}% সম্পন্ন)",
            f"• সক্রিয় অভ্যাস ট্র্যাকিং: **{len(habits)}টি**",
            f"• সক্রিয় লক্ষ্য ট্র্যাকিং: **{len(active_goals)}টি**\n",
            "🏆 **অভ্যাস হাইলাইটস:**",
        ]

        for h in habits[:3]:
            lines.append(f"• `{h.name}`: বর্তমান {h.current_streak} দিন (সর্বোচ্চ: {h.best_streak} দিন)")

        lines.append("\n🎯 **লক্ষ্য অগ্রগতি:**")
        for g in active_goals[:3]:
            lines.append(f"• `{g.title}`: **{g.progress_pct}%**")

        lines.append("\nসুস্থ ও সফল সপ্তাহ কাটুক, বস!")
        return "\n".join(lines)

    def detect_commitments(self, message: str) -> list[dict[str, str]]:
        """Scan user messages for promised actions or commitments and create follow-up candidates."""
        if not message or not message.strip():
            return []

        detected: list[dict[str, str]] = []
        for pattern, kind in self.COMMITMENT_PATTERNS:
            for match in re.finditer(pattern, message, re.IGNORECASE):
                action = match.group(1).strip()
                detected.append({
                    "kind": kind,
                    "action": action,
                    "raw_match": match.group(0),
                })
        return detected
