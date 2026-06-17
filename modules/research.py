"""Research agent: generate structured summaries via Groq."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.ai import AruAI
    from modules.activity_log import ActivityLogger
    from modules.memory import MemoryStore

logger = logging.getLogger("aru.research")

RESEARCH_SYSTEM_ADDENDUM = """
You are operating as Aru's Research Agent.
Produce a clear, well-structured research summary with:
1. Executive summary (2-3 sentences)
2. Key points (bullet list)
3. Practical implications or next steps for Boss
4. Limitations — note if live web data is unavailable
Be factual, concise, and actionable. Use the same language as the research topic.
"""


class ResearchAgent:
    """Generate research summaries on demand."""

    def __init__(self, ai: "AruAI", activity: "ActivityLogger | None" = None) -> None:
        self._ai = ai
        self._activity = activity

    async def research(
        self,
        topic: str,
        *,
        memory: "MemoryStore | None" = None,
    ) -> str:
        """Run a research query and return a formatted summary."""
        topic = topic.strip()
        if not topic:
            return "ব্যবহার: `/research <বিষয়>`"

        memory_ctx = ""
        if memory:
            memory_ctx = memory.context_for_ai(topic, limit=5)

        prompt = (
            f"Research topic: {topic}\n\n"
            "Provide a comprehensive research summary for my Boss. "
            "Include background, key findings, trends, and recommended actions."
        )

        logger.info("Research started | topic=%s", topic[:80])
        if self._activity:
            self._activity.log("research", "start", topic[:200])

        try:
            summary = await self._ai.generate(
                prompt,
                memory_context=self._build_context(memory_ctx),
                max_tokens=4096,
            )
            if self._activity:
                self._activity.log(
                    "research",
                    "complete",
                    f"topic={topic[:80]} len={len(summary)}",
                )
            logger.info("Research complete | topic=%s len=%s", topic[:40], len(summary))
            return f"📚 **Research: {topic}**\n\n{summary}"
        except Exception as exc:
            if self._activity:
                self._activity.log_error("research", "complete", exc)
            logger.exception("Research failed: %s", exc)
            return (
                f"দুঃখিত বস, '{topic}' নিয়ে রিসার্চ করতে পারিনি। "
                "কিছুক্ষণ পর আবার চেষ্টা করুন।"
            )

    def _build_context(self, memory_ctx: str) -> str:
        parts = [RESEARCH_SYSTEM_ADDENDUM.strip()]
        if memory_ctx:
            parts.append(f"Related Boss memories:\n{memory_ctx}")
        return "\n\n".join(parts)

    def handle_command(self, text: str, *, memory: "MemoryStore | None" = None) -> str | None:
        """Parse /research <topic> — returns coroutine payload marker or None."""
        stripped = text.strip()
        if not stripped.lower().startswith("/research"):
            return None
        topic = stripped.split(maxsplit=1)[1] if " " in stripped else ""
        if not topic:
            return "ব্যবহার: `/research <বিষয়>`\nউদাহরণ: `/research Python async best practices`"
        return f"__RESEARCH__:{topic}"

    async def handle_command_async(
        self,
        text: str,
        *,
        memory: "MemoryStore | None" = None,
    ) -> str | None:
        """Async handler for /research commands."""
        stripped = text.strip()
        if not stripped.lower().startswith("/research"):
            return None
        topic = stripped.split(maxsplit=1)[1] if " " in stripped else ""
        if not topic:
            return "ব্যবহার: `/research <বিষয়>`"
        return await self.research(topic, memory=memory)
