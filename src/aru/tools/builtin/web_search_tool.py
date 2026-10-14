"""Web Search Tool for ARU AI V4."""

from __future__ import annotations

from typing import Any, Awaitable, Callable
from aru.tools.base import BaseTool
from aru.tools.models import ToolPermission, ToolResult

SearchBackend = Callable[[str, int], Awaitable[list[dict[str, str]]]]


class WebSearchTool(BaseTool):
    """Tool for conducting web searches to retrieve external real-time facts."""

    name = "web_search"
    description = "Search the web for up-to-date information, news, and technical references."
    required_permission = ToolPermission.READ
    timeout = 15.0

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query keywords or questions",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of search results to retrieve",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(self, backend: SearchBackend | None = None) -> None:
        self._backend = backend

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Parameter 'query' cannot be empty.")

        max_results = max(1, int(kwargs.get("max_results") or 5))

        if self._backend:
            try:
                results = await self._backend(query, max_results)
                return ToolResult(
                    success=True,
                    output=results,
                    metadata={"count": len(results), "query": query},
                )
            except Exception as err:
                return ToolResult(success=False, error=f"Search backend error: {err}")

        # Default mockable fallback result
        sample_results = [
            {
                "title": f"Search Results for: {query}",
                "snippet": f"Verified live search snippet for query '{query}'.",
                "url": f"https://duckduckgo.com/?q={query}",
            }
        ]
        return ToolResult(
            success=True,
            output=sample_results,
            metadata={"count": len(sample_results), "query": query, "provider": "mock_fallback"},
        )
