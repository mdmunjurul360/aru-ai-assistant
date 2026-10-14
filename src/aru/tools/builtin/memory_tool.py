"""Memory Tool for ARU AI V4."""

from __future__ import annotations

from typing import Any
from aru.memory.interfaces import IMemoryService, IPersistentMemory
from aru.tools.base import BaseTool
from aru.tools.models import ToolPermission, ToolResult


class MemoryTool(BaseTool):
    """Tool for querying, remembering, and managing episodic long-term facts."""

    name = "memory"
    description = "Store, recall, search, or delete persistent facts, user preferences, and memories."
    required_permission = ToolPermission.READ
    timeout = 10.0

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save", "search", "recall", "delete"],
                "description": "Action to perform on memory store",
            },
            "content": {
                "type": "string",
                "description": "Information to remember (required for 'save')",
            },
            "query": {
                "type": "string",
                "description": "Keywords or question to search (required for 'search' and 'recall')",
            },
            "key": {
                "type": "string",
                "description": "Unique identifier for the memory item",
            },
            "category": {
                "type": "string",
                "description": "Category (e.g., preference, project, personal, general)",
                "default": "general",
            },
            "limit": {
                "type": "integer",
                "description": "Max search results to return",
                "default": 5,
            },
        },
        "required": ["action"],
    }

    def __init__(self, memory_service: IMemoryService | None = None, persistent_memory: IPersistentMemory | None = None) -> None:
        self._service = memory_service
        self._persistent = persistent_memory

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()

        if action == "save":
            content = kwargs.get("content", "").strip()
            if not content:
                return ToolResult(success=False, error="Parameter 'content' is required for action 'save'.")

            key = kwargs.get("key")
            category = kwargs.get("category", "general")

            if self._service:
                row_id = await self._service.remember(content=content, key=key, category=category)
            elif self._persistent:
                row_id = await self._persistent.store_fact(content=content, key=key, category=category)
            else:
                return ToolResult(success=False, error="Memory storage service is not available.")

            return ToolResult(
                success=True,
                output=f"Successfully stored memory (id={row_id}, key={key or 'auto'}).",
                metadata={"id": row_id, "key": key},
            )

        elif action in ("search", "recall"):
            query = kwargs.get("query", "").strip()
            if not query:
                return ToolResult(success=False, error="Parameter 'query' is required for search.")

            limit = int(kwargs.get("limit") or 5)
            if self._service:
                facts = await self._service.recall(query=query, limit=limit)
            elif self._persistent:
                facts = await self._persistent.search_facts(query=query, limit=limit)
            else:
                return ToolResult(success=False, error="Memory storage service is not available.")

            formatted = [
                {"id": f.id, "key": f.key, "category": f.category, "content": f.content}
                for f in facts
            ]
            return ToolResult(
                success=True,
                output=formatted,
                metadata={"count": len(formatted)},
            )

        elif action == "delete":
            key = kwargs.get("key", "").strip()
            if not key:
                return ToolResult(success=False, error="Parameter 'key' is required for delete.")

            if self._persistent:
                deleted = await self._persistent.delete_fact(key)
                if deleted:
                    return ToolResult(success=True, output=f"Memory '{key}' deleted successfully.")
                return ToolResult(success=False, error=f"Memory '{key}' not found.")
            return ToolResult(success=False, error="Persistent memory service not available.")

        return ToolResult(success=False, error=f"Unsupported memory action '{action}'.")
