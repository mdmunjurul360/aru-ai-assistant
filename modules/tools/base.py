"""Base abstractions for Sprint 4 Integration Layer: Tool Registry & MCP architecture."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("aru.tools")


class ToolPermission(str, Enum):
    """Permission levels required to invoke a tool."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"

    @property
    def level(self) -> int:
        levels = {
            ToolPermission.READ: 10,
            ToolPermission.WRITE: 20,
            ToolPermission.EXECUTE: 30,
            ToolPermission.ADMIN: 40,
        }
        return levels.get(self, 0)

    def is_authorized_by(self, granted: ToolPermission) -> bool:
        return granted.level >= self.level


@dataclass
class ExecutionContext:
    """Context accompanying a tool execution request."""
    user_id: int
    is_boss: bool = False
    caller: str = "telegram"
    permissions: set[ToolPermission] = field(default_factory=set)
    extra: dict[str, Any] = field(default_factory=dict)

    def has_permission(self, required: ToolPermission) -> bool:
        """Check if context holds the necessary permission."""
        if self.is_boss:
            return True
        if ToolPermission.ADMIN in self.permissions:
            return True
        return any(required.is_authorized_by(p) for p in self.permissions)


@dataclass
class ToolResult:
    """Standardized output returned by every tool execution."""
    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }

    def format_output(self) -> str:
        """Return a user-friendly string representation of the tool output."""
        if not self.success:
            return f"❌ ত্রুটি: {self.error or 'অজানা ত্রুটি'}"

        if isinstance(self.output, str):
            return self.output
        if isinstance(self.output, (dict, list)):
            import json
            try:
                return json.dumps(self.output, ensure_ascii=False, indent=2)
            except Exception:
                return str(self.output)
        if self.output is None:
            return "সফলভাবে সম্পন্ন হয়েছে (কোনো আউটপুট নেই)।"
        return str(self.output)


class BaseTool(ABC):
    """
    Abstract base class for all tools in Aru AI's Integration Layer.
    Adheres to Model Context Protocol (MCP) and function calling standards.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    required_permission: ToolPermission = ToolPermission.READ
    timeout: float = 30.0

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute tool action with validated kwargs and return ToolResult."""
        raise NotImplementedError

    def to_mcp_schema(self) -> dict[str, Any]:
        """Export tool definition in standard MCP / OpenAI Tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
            "required_permission": self.required_permission.value,
            "timeout": self.timeout,
        }

    def validate_input(self, args: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate input arguments against tool parameters JSON schema.
        Performs required fields checking, type checking, and enum constraints.
        """
        schema = self.parameters
        if not schema or schema.get("type") != "object":
            return True, None

        required = schema.get("required", [])
        for field_name in required:
            if field_name not in args:
                return False, f"Missing required parameter '{field_name}'"

        properties = schema.get("properties", {})
        for key, val in args.items():
            if key in properties:
                prop_spec = properties[key]
                expected_type = prop_spec.get("type")
                if expected_type == "string" and not isinstance(val, str):
                    return False, f"Parameter '{key}' must be a string, got {type(val).__name__}"
                if expected_type == "integer" and not (isinstance(val, int) and not isinstance(val, bool)):
                    return False, f"Parameter '{key}' must be an integer, got {type(val).__name__}"
                if expected_type == "boolean" and not isinstance(val, bool):
                    return False, f"Parameter '{key}' must be a boolean, got {type(val).__name__}"
                if expected_type == "array" and not isinstance(val, list):
                    return False, f"Parameter '{key}' must be a list/array, got {type(val).__name__}"
                if expected_type == "object" and not isinstance(val, dict):
                    return False, f"Parameter '{key}' must be an object/dict, got {type(val).__name__}"

                enums = prop_spec.get("enum")
                if enums is not None and val not in enums:
                    return False, f"Parameter '{key}' value '{val}' is not in allowed choices: {enums}"

        return True, None
