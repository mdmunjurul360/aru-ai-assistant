"""Token optimization and dynamic token allocation for Aru AI."""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any

logger = logging.getLogger("aru.token_optimizer")


class TaskType(str, Enum):
    CHAT = "chat"
    CODING = "coding"
    SUMMARIZATION = "summarization"
    PDF_CHUNK = "pdf_chunk"
    PDF_FINAL = "pdf_final"
    VISION = "vision"


# Max output token limits recommended per task type
TASK_TOKEN_BUDGETS: dict[TaskType, int] = {
    TaskType.CHAT: 1536,
    TaskType.CODING: 3584,
    TaskType.SUMMARIZATION: 1536,
    TaskType.PDF_CHUNK: 512,
    TaskType.PDF_FINAL: 1536,
    TaskType.VISION: 800,
}

# Hardware / API provider hard caps on output generation tokens
PROVIDER_MAX_OUTPUT_LIMITS: dict[str, int] = {
    "gemini": 8192,
    "groq": 4096,
    "deepseek": 4096,
    "openai": 4096,
}

_CODE_PATTERNS = re.compile(
    r"\b(def |class |import |function |const |let |var |```|public |private |fn |SELECT |CREATE |table |git |docker |pytest |unittest |lambda |traceback |syntaxerror |bug |refactor |implement)\b",
    re.IGNORECASE,
)

_SUMMARY_PATTERNS = re.compile(
    r"\b(summarize|summary|সারসংক্ষেপ|সংক্ষেপ|overview|key points|tldr|bullet points|abstract|brief)\b",
    re.IGNORECASE,
)


def detect_task_type(prompt: str, explicit_type: TaskType | str | None = None) -> TaskType:
    """Classify the user prompt to apply optimal generation limits."""
    if explicit_type:
        if isinstance(explicit_type, TaskType):
            return explicit_type
        try:
            return TaskType(str(explicit_type).lower())
        except ValueError:
            pass

    text = prompt or ""
    if _CODE_PATTERNS.search(text):
        return TaskType.CODING
    if _SUMMARY_PATTERNS.search(text):
        return TaskType.SUMMARIZATION

    return TaskType.CHAT


def get_optimal_max_tokens(
    prompt: str | TaskType = "",
    *,
    task_type: TaskType | str | None = None,
    provider: str | None = None,
    requested_tokens: int | None = None,
    max_tokens: int | None = None,
) -> int:
    """
    Dynamically select appropriate max output tokens.
    Guarantees that the value never exceeds provider limits or wastes bandwidth.
    """
    if isinstance(prompt, TaskType):
        task_type = prompt
        prompt = ""

    req = requested_tokens or max_tokens
    detected_type = detect_task_type(str(prompt), explicit_type=task_type)
    default_budget = TASK_TOKEN_BUDGETS.get(detected_type, 1536)

    # If caller requested tokens explicitly, respect it up to reasonable bounds
    target = req if (req and req > 0) else default_budget

    # Never exceed the provider's max output token ceiling
    if provider:
        p_clean = provider.strip().lower()
        limit = PROVIDER_MAX_OUTPUT_LIMITS.get(p_clean, 4096)
        target = min(target, limit)

    return target


def estimate_tokens(text: str) -> int:
    """Fast, dependency-free token estimation for context budgets."""
    if not text:
        return 0
    # Average ~3.5 chars per token for English/code, ~2 for Bengali/Unicode
    return max(1, len(text) // 3)
