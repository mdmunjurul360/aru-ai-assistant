"""Semantic Context Compression for Aru AI."""

from __future__ import annotations

import re
from typing import Sequence

from modules.semantic_memory.hybrid_search import HybridSearchResult


class ContextCompressor:
    """
    Compresses long-term memory snippets and conversational histories
    into high-density prompt contexts while minimizing LLM token consumption.
    """

    def __init__(self, max_token_budget: int = 1200) -> None:
        self.max_token_budget = max_token_budget

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimate (~4 chars per token for English/code, ~2 for unicode)."""
        if not text:
            return 0
        return max(1, len(text) // 3)

    def compress_memory_results(
        self,
        results: Sequence[HybridSearchResult],
        max_items: int = 6,
    ) -> str:
        """
        Compress hybrid search results into clean markdown facts.
        Prunes repetitive phrasing, strips excessive whitespace, and prioritizes top RRF items.
        """
        if not results:
            return ""

        compressed_lines: list[str] = []
        current_tokens = 0

        for res in results[:max_items]:
            # Compact text: collapse multiple spaces and newlines
            clean_content = re.sub(r"\s+", " ", res.content).strip()
            # If content is excessively long, preserve head and tail
            if len(clean_content) > 350:
                clean_content = clean_content[:200] + " ... " + clean_content[-100:]

            line = f"• [{res.category.upper()}] {res.title}: {clean_content}"
            line_tokens = self.estimate_tokens(line)

            if current_tokens + line_tokens > self.max_token_budget:
                break

            compressed_lines.append(line)
            current_tokens += line_tokens

        return "\n".join(compressed_lines)

    def compress_conversation_history(
        self,
        history: list[dict[str, str]],
        max_turns: int = 6,
    ) -> list[dict[str, str]]:
        """
        Compress multi-turn dialogue into high-signal messages.
        Keeps the latest turns intact and summarizes/truncates older verbose turns.
        """
        if not history:
            return []

        recent = history[-max_turns:]
        compressed: list[dict[str, str]] = []

        for idx, msg in enumerate(recent):
            role = msg.get("role", "user")
            content = msg.get("content", "").strip()

            # For older messages in the window, compress lengthy assistant outputs
            if idx < len(recent) - 1 and role == "assistant" and len(content) > 400:
                content = content[:250] + " ... [trimmed]"

            compressed.append({"role": role, "content": content})

        return compressed
