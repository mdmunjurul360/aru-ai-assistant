"""Research Tool for Sprint 4 Integration Layer: wraps grounded research engine."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from modules.tools.base import BaseTool, ToolPermission, ToolResult

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.research_service import ResearchService

logger = logging.getLogger("aru.tools.research")


class ResearchTool(BaseTool):
    """
    Exposes the Grounded Research Engine as a modular MCP-compatible tool.
    Supports verified multi-engine web search, content scraping, and cached knowledge lookups.
    """

    name = "research"
    description = (
        "Search the web with source verification, scrape web pages, and retrieve "
        "cached research summaries for accurate, grounded knowledge."
    )
    required_permission = ToolPermission.READ
    timeout = 45.0

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "scrape", "cached_search"],
                "description": "Action: 'search' (web search + AI summary), 'scrape' (extract URL text), 'cached_search' (cache lookup).",
            },
            "query": {
                "type": "string",
                "description": "Search query or topic to research.",
            },
            "url": {
                "type": "string",
                "description": "Direct URL to scrape (required if action is 'scrape').",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of web search results to consider (default 5).",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        research_service: ResearchService | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        self.service = research_service
        self.activity = activity

    def _ensure_service(self) -> ResearchService:
        if self.service is None:
            from modules.ai import AruAI
            from modules.research_service import ResearchService
            self.service = ResearchService(ai=AruAI(), activity=self.activity)
        return self.service

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "search")
        query = kwargs.get("query", "").strip()
        url = kwargs.get("url", "").strip()
        max_results = int(kwargs.get("max_results", 5))

        service = self._ensure_service()

        if action == "scrape":
            if not url:
                return ToolResult(
                    success=False,
                    error="Parameter 'url' is required when action is 'scrape'.",
                )
            try:
                page_data = await service.scrape_url(url)
                if not page_data or not page_data.get("content"):
                    return ToolResult(
                        success=False,
                        error=f"Failed to extract content from {url}",
                        metadata={"url": url},
                    )
                return ToolResult(
                    success=True,
                    output=page_data.get("content"),
                    metadata={
                        "url": url,
                        "title": page_data.get("title", ""),
                        "status_code": page_data.get("status_code"),
                    },
                )
            except Exception as exc:
                return ToolResult(
                    success=False,
                    error=f"Scrape error: {exc}",
                    metadata={"url": url},
                )

        if action == "cached_search":
            if not query:
                return ToolResult(
                    success=False,
                    error="Parameter 'query' is required for 'cached_search'.",
                )
            cached = service.cache.get(query)
            if not cached:
                return ToolResult(
                    success=True,
                    output=None,
                    metadata={"query": query, "found": False},
                )
            return ToolResult(
                success=True,
                output=cached.get("summary", ""),
                metadata={"query": query, "found": True, "cached_at": cached.get("created_at")},
            )

        # Default action: search
        if not query:
            return ToolResult(
                success=False,
                error="Parameter 'query' is required for 'search'.",
            )

        try:
            report = await service.research(query, max_results=max_results)
            formatted = service.format_report(report)
            return ToolResult(
                success=True,
                output=formatted,
                metadata={
                    "query": query,
                    "confidence": report.confidence_score,
                    "source_count": len(report.sources),
                    "cached": report.cached,
                    "provider": report.provider_used,
                },
            )
        except Exception as exc:
            logger.exception("Research execution error: %s", exc)
            return ToolResult(
                success=False,
                error=f"Research failed: {exc}",
                metadata={"query": query},
            )
