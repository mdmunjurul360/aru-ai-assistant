"""Autonomous Learning package: Preference profile, Behavior analyzer, and Automation suggester."""

from __future__ import annotations

from modules.learning.automation_suggester import (
    AutomationSuggester,
    AutomationSuggestion,
)
from modules.learning.behavior_analyzer import (
    BehaviorAnalyzer,
    BehaviorPattern,
)
from modules.learning.preference_learner import (
    PreferenceLearner,
    UserPreference,
)

__all__ = [
    "PreferenceLearner",
    "UserPreference",
    "BehaviorAnalyzer",
    "BehaviorPattern",
    "AutomationSuggester",
    "AutomationSuggestion",
]
