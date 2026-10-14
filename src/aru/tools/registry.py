"""Tool registry for ARU AI V4."""

from __future__ import annotations

import threading
from typing import Any
from aru.tools.base import BaseTool


class ToolRegistry:
    """Central registry managing tool discovery, schemas, and life cycle."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._lock = threading.Lock()

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if not isinstance(tool, BaseTool):
            raise TypeError(f"Expected BaseTool instance, got {type(tool).__name__}")
        if not tool.name or not tool.name.strip():
            raise ValueError("Tool name must be a non-empty string.")
        if not tool.description:
            raise ValueError(f"Tool '{tool.name}' must have a description.")

        with self._lock:
            self._tools[tool.name.strip().lower()] = tool

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name."""
        with self._lock:
            return self._tools.pop(name.strip().lower(), None) is not None

    def get(self, name: str) -> BaseTool | None:
        """Retrieve registered tool by name."""
        with self._lock:
            return self._tools.get(name.strip().lower())

    def has(self, name: str) -> bool:
        """Check whether tool name is registered."""
        with self._lock:
            return name.strip().lower() in self._tools

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        with self._lock:
            return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI/Groq function calling schemas for all registered tools."""
        with self._lock:
            return [tool.to_function_schema() for tool in self._tools.values()]

    def count(self) -> int:
        """Return total registered tool count."""
        with self._lock:
            return len(self._tools)
