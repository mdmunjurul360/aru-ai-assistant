"""Abstract base tool interface for ARU AI V4."""

from __future__ import annotations

import abc
from typing import Any
from aru.tools.models import ToolPermission, ToolResult


class BaseTool(abc.ABC):
    """
    Abstract base class for all tools in ARU AI V4.
    Adheres to Model Context Protocol (MCP) and LLM function calling standards.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    required_permission: ToolPermission = ToolPermission.READ
    timeout: float = 30.0

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool logic with provided arguments."""
        raise NotImplementedError

    def to_function_schema(self) -> dict[str, Any]:
        """Generate OpenAI/Groq standard function-calling JSON schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate_arguments(self, kwargs: dict[str, Any]) -> list[str]:
        """Basic validation checking that required parameters are present."""
        errors: list[str] = []
        required = self.parameters.get("required", [])
        for field in required:
            if field not in kwargs or kwargs[field] is None:
                errors.append(f"Missing required argument: '{field}'")
        return errors
