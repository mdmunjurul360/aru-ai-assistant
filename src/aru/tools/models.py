"""Models and permissions for ARU AI V4 Tool System."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


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
        """Check if granted permission is greater than or equal to this requirement."""
        return granted.level >= self.level


class ExecutionContext(BaseModel):
    """Context accompanying a tool execution request."""

    model_config = ConfigDict(frozen=True)

    user_id: int
    is_boss: bool = False
    caller: str = "core"
    permissions: set[ToolPermission] = Field(default_factory=set)
    extra: dict[str, Any] = Field(default_factory=dict)

    def has_permission(self, required: ToolPermission) -> bool:
        """Check whether context holds the required permission level."""
        if self.is_boss:
            return True
        if ToolPermission.ADMIN in self.permissions:
            return True
        return any(required.is_authorized_by(p) for p in self.permissions)


class ToolResult(BaseModel):
    """Standardized output returned by every tool execution."""

    model_config = ConfigDict(frozen=True)

    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def format_output(self) -> str:
        """Return a user-friendly string representation of the tool output."""
        if not self.success:
            return f"❌ Error: {self.error or 'Unknown error'}"

        if isinstance(self.output, str):
            return self.output
        if isinstance(self.output, (dict, list)):
            try:
                return json.dumps(self.output, ensure_ascii=False, indent=2)
            except Exception:
                return str(self.output)
        if self.output is None:
            return "Operation completed successfully (no output)."
        return str(self.output)
