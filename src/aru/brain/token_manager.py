"""Token budgeting and context window compression for ARU AI V4."""

from __future__ import annotations

from aru.brain.models import LLMMessage


class TokenBudgetManager:
    """
    Calculates estimated token counts and prunes conversation messages
    to fit within context window limits while preserving system instructions.
    """

    MESSAGE_OVERHEAD_TOKENS = 4
    BASE_COMPLETION_OVERHEAD = 3

    @classmethod
    def estimate_text_tokens(cls, text: str) -> int:
        """Estimate tokens from text length (heuristic ~4 chars per token)."""
        if not text:
            return 0
        return max(1, (len(text) // 4) + 1)

    @classmethod
    def estimate_message_tokens(cls, message: LLMMessage) -> int:
        """Estimate token cost for a single chat message."""
        content_tokens = cls.estimate_text_tokens(message.content)
        name_tokens = cls.estimate_text_tokens(message.name) if message.name else 0
        return content_tokens + name_tokens + cls.MESSAGE_OVERHEAD_TOKENS

    @classmethod
    def estimate_messages_tokens(cls, messages: list[LLMMessage]) -> int:
        """Estimate total tokens across a list of messages."""
        if not messages:
            return 0
        total = cls.BASE_COMPLETION_OVERHEAD
        for m in messages:
            total += cls.estimate_message_tokens(m)
        return total

    @classmethod
    def fit_messages(
        cls,
        messages: list[LLMMessage],
        max_tokens: int,
    ) -> list[LLMMessage]:
        """
        Prune older messages to ensure total tokens stay below max_tokens.
        Always preserves the leading 'system' message if present.
        """
        if not messages:
            return []

        total_cost = cls.estimate_messages_tokens(messages)
        if total_cost <= max_tokens:
            return list(messages)

        has_system = messages[0].role == "system"
        system_msg = messages[0] if has_system else None
        conversation_msgs = messages[1:] if has_system else messages

        budget = max_tokens - (cls.estimate_message_tokens(system_msg) if system_msg else 0) - cls.BASE_COMPLETION_OVERHEAD
        if budget <= 0:
            return [system_msg] if system_msg else []

        fitted_conv: list[LLMMessage] = []
        accumulated = 0

        # Iterate backwards from newest message
        for msg in reversed(conversation_msgs):
            cost = cls.estimate_message_tokens(msg)
            if accumulated + cost > budget and fitted_conv:
                break
            fitted_conv.append(msg)
            accumulated += cost

        result: list[LLMMessage] = []
        if system_msg:
            result.append(system_msg)
        result.extend(reversed(fitted_conv))
        return result
