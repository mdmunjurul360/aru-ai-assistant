"""ResearchAgent: backward-compatible adapter over the production ResearchService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from modules.research_service import (
    Citation,
    JobListing,
    ResearchResult,
    ResearchService,
)

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.ai import AruAI
    from modules.memory import MemoryStore

logger = logging.getLogger("aru.research")


class ResearchAgent:
    """
    Research Agent facade for Aru AI.
    
    Provides backward-compatible command handlers while delegating all
    live web retrieval, source verification, and structured citations
    to the production ResearchService layer.
    """

    def __init__(
        self,
        ai: "AruAI",
        activity: "ActivityLogger | None" = None,
        service: ResearchService | None = None,
    ) -> None:
        self._ai = ai
        self._activity = activity
        self.service = service or ResearchService(ai, activity=activity)

    async def research(
        self,
        topic: str,
        *,
        memory: "MemoryStore | None" = None,
        bypass_cache: bool = False,
    ) -> str:
        """
        Execute research pipeline and return Telegram-formatted markdown.
        Preserves backward-compatible string return signature.
        """
        topic = topic.strip()
        if not topic:
            return "ব্যবহার: `/research <বিষয়>`"

        memory_ctx = ""
        if memory:
            memory_ctx = memory.context_for_ai(topic, limit=5)

        res = await self.service.execute_research(
            topic,
            bypass_cache=bypass_cache,
            memory_context=memory_ctx,
        )
        return res.formatted_markdown()

    async def research_structured(
        self,
        topic: str,
        *,
        memory: "MemoryStore | None" = None,
        bypass_cache: bool = False,
    ) -> ResearchResult:
        """Execute research and return structured ResearchResult dataclass."""
        memory_ctx = ""
        if memory:
            memory_ctx = memory.context_for_ai(topic, limit=5)

        return await self.service.execute_research(
            topic,
            bypass_cache=bypass_cache,
            memory_context=memory_ctx,
        )

    def handle_command(self, text: str, *, memory: "MemoryStore | None" = None) -> str | None:
        """Parse /research <topic> — returns coroutine payload marker or help."""
        stripped = text.strip()
        if not stripped.lower().startswith("/research"):
            return None
        topic = stripped.split(maxsplit=1)[1] if " " in stripped else ""
        if not topic:
            return "ব্যবহার: `/research <বিষয়>`\nউদাহরণ: `/research Python async best practices`\nক্যাশ বাইপাস: `/research --refresh <বিষয়>`"
        return f"__RESEARCH__:{topic}"

    async def handle_command_async(
        self,
        text: str,
        *,
        memory: "MemoryStore | None" = None,
    ) -> str | None:
        """Async handler for /research commands from Telegram dispatcher."""
        stripped = text.strip()
        if not stripped.lower().startswith("/research"):
            return None
        topic = stripped.split(maxsplit=1)[1] if " " in stripped else ""
        if not topic:
            return "ব্যবহার: `/research <বিষয়>`"

        bypass_cache = False
        if topic.startswith("--refresh "):
            bypass_cache = True
            topic = topic[10:].strip()
        elif topic.startswith("refresh "):
            bypass_cache = True
            topic = topic[8:].strip()

        return await self.research(topic, memory=memory, bypass_cache=bypass_cache)

    async def _verify_job_url(self, url: str) -> dict | None:
        """Legacy helper for link verification (backward compatibility)."""
        is_alive = await ResearchService.validate_link(url)
        if not is_alive:
            return None
        return {
            "title": "Verified Job Listing",
            "company": "—",
            "location": "Remote",
            "url": url,
        }
