"""Memory Tool for Sprint 4 Integration Layer: wraps SQLite FTS5 persistent memory."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from modules.memory import CATEGORIES
from modules.tools.base import BaseTool, ToolPermission, ToolResult

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.memory_service import MemoryService

logger = logging.getLogger("aru.tools.memory")


class MemoryTool(BaseTool):
    """
    Exposes persistent SQLite FTS5 memory management as an MCP-compatible tool.
    Supports BM25 ranked search, storing long-term facts, listing, and memory deletion.
    """

    name = "memory"
    description = (
        "Persistent memory management. Search facts with FTS5 BM25 ranking, "
        "save new knowledge, list categories, or delete obsolete memories."
    )
    required_permission = ToolPermission.READ
    timeout = 15.0

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "save", "list", "delete"],
                "description": "Action: 'search' (keyword search), 'save' (store fact), 'list' (view items), 'delete' (remove by ID).",
            },
            "query": {
                "type": "string",
                "description": "Query term for searching stored memories.",
            },
            "content": {
                "type": "string",
                "description": "Fact or knowledge text to store (required for 'save').",
            },
            "title": {
                "type": "string",
                "description": "Optional title for the memory item.",
            },
            "category": {
                "type": "string",
                "description": f"Memory category: {', '.join(CATEGORIES)}. Defaults to 'fact'.",
            },
            "tags": {
                "type": "string",
                "description": "Optional comma-separated tags.",
            },
            "id": {
                "type": "integer",
                "description": "Memory ID to delete (required for 'delete').",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to retrieve (default 5).",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        memory_service: MemoryService | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        self.service = memory_service
        self.activity = activity

    def _ensure_service(self) -> MemoryService:
        if self.service is None:
            from modules.activity_log import ActivityLogger
            from modules.conversation import ConversationHistoryStore
            from modules.memory import MemoryStore
            from modules.memory_service import MemoryService

            act = self.activity or ActivityLogger()
            mem = MemoryStore(activity=act)
            conv = ConversationHistoryStore(db_path=mem.db_path)
            self.service = MemoryService(memory_store=mem, conversation_store=conv, activity=act)
        return self.service

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "search")
        service = self._ensure_service()
        limit = min(int(kwargs.get("limit", 5)), 50)

        # 1. Search action
        if action == "search":
            query = kwargs.get("query", "").strip()
            if not query:
                return ToolResult(
                    success=False,
                    error="Parameter 'query' is required for action 'search'.",
                )
            items = service.search_memory(query, limit=limit)
            formatted = service.memory_store.format_list(items)
            output_list = [
                {
                    "id": item.id,
                    "title": item.title,
                    "content": item.content,
                    "category": item.category,
                    "tags": item.tags,
                    "rank": getattr(item, "rank", None),
                }
                for item in items
            ]
            return ToolResult(
                success=True,
                output=formatted,
                metadata={"items": output_list, "count": len(items), "query": query},
            )

        # 2. Save action
        if action == "save":
            content = kwargs.get("content", "").strip()
            if not content:
                return ToolResult(
                    success=False,
                    error="Parameter 'content' is required for action 'save'.",
                )
            title = kwargs.get("title", "").strip()
            category = kwargs.get("category", "fact").strip().lower()
            tags = kwargs.get("tags", "").strip()

            if title:
                item = service.memory_store.save(
                    title=title,
                    content=content,
                    category=category,
                    tags=tags or category,
                )
            else:
                item = service.store_fact(content, category=category, tags=tags or category)

            return ToolResult(
                success=True,
                output=f"মেমোরি সংরক্ষিত ✅\n\n{service.memory_store.format_item(item)}",
                metadata={"id": item.id, "title": item.title, "category": item.category},
            )

        # 3. List action
        if action == "list":
            category = kwargs.get("category")
            if category:
                category = category.strip().lower()
            items = service.memory_store.list_all(category=category, limit=limit)
            formatted = service.memory_store.format_list(items)
            return ToolResult(
                success=True,
                output=formatted,
                metadata={"count": len(items), "category": category},
            )

        # 4. Delete action
        if action == "delete":
            mem_id = kwargs.get("id")
            if mem_id is None:
                return ToolResult(
                    success=False,
                    error="Parameter 'id' is required for action 'delete'.",
                )
            success = service.memory_store.delete(int(mem_id))
            if success:
                return ToolResult(
                    success=True,
                    output=f"মেমোরি #{mem_id} মুছে ফেলা হয়েছে।",
                    metadata={"deleted_id": mem_id},
                )
            return ToolResult(
                success=False,
                error=f"মেমোরি #{mem_id} পাওয়া যায়নি।",
                metadata={"target_id": mem_id},
            )

        return ToolResult(
            success=False,
            error=f"Unknown memory action: '{action}'",
        )
