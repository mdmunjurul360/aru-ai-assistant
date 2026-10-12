"""Proactive automation suggestions based on learned user behaviors."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from modules.learning.behavior_analyzer import BehaviorAnalyzer, BehaviorPattern
from modules.learning.preference_learner import PreferenceLearner

logger = logging.getLogger("aru.learning.automation_suggester")


@dataclass
class AutomationSuggestion:
    """A proactive automation recipe recommended to the user."""
    suggestion_id: str
    title: str
    description: str
    trigger_type: str  # "schedule", "event", "command_macro"
    recommended_action: str
    confidence: float

    def format_card(self) -> str:
        return (
            f"💡 **প্রস্তাবিত অটোমেশন (Suggestion): {self.title}**\n"
            f"• বিবরণ: {self.description}\n"
            f"• প্রকার: `{self.trigger_type}` | আত্মবিশ্বাস: `{int(self.confidence * 100)}%`\n"
            f"• প্রস্তাবিত অ্যাকশন: `{self.recommended_action}`"
        )


class AutomationSuggester:
    """
    Generates intelligent workflow automation suggestions by fusing
    learned preferences with observed behavioral patterns.
    """

    def __init__(
        self,
        behavior_analyzer: BehaviorAnalyzer,
        preference_learner: PreferenceLearner,
    ) -> None:
        self.analyzer = behavior_analyzer
        self.learner = preference_learner

    def generate_suggestions(self) -> list[AutomationSuggestion]:
        patterns = self.analyzer.analyze_patterns(min_frequency=2)
        suggestions: list[AutomationSuggestion] = []

        for p in patterns:
            if "research" in p.action_key or "search" in p.action_key:
                suggestions.append(
                    AutomationSuggestion(
                        suggestion_id="sugg_daily_research",
                        title="দৈনিক স্বয়ংক্রিয় রিসার্চ আপডেট",
                        description="আপনি প্রায়ই নতুন তথ্য ও রিসার্চ সার্চ করেন। প্রতি সকালে এটি স্বয়ংক্রিয়ভাবে রান করার সুপারিশ করছি।",
                        trigger_type="schedule",
                        recommended_action="/workflow research_update",
                        confidence=p.confidence,
                    )
                )
            elif "tasks" in p.action_key or "task" in p.action_key:
                suggestions.append(
                    AutomationSuggestion(
                        suggestion_id="sugg_morning_briefing",
                        title="সকালের টাস্ক ব্রিফিং ও ফলো-আপ",
                        description="আপনি নিয়মিত টাস্ক তৈরি ও পরিচালনা করেন। সকালের ব্রিফিং আপনাকে পেন্ডিং কাজের তালিকা দেখাবে।",
                        trigger_type="schedule",
                        recommended_action="/workflow morning_briefing",
                        confidence=p.confidence,
                    )
                )

        # Deduplicate suggestions by suggestion_id
        seen = set()
        deduped = []
        for s in suggestions:
            if s.suggestion_id not in seen:
                seen.add(s.suggestion_id)
                deduped.append(s)

        return deduped
