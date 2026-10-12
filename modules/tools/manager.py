"""Tool Manager for Sprint 4 Integration Layer: discovery, permissions, and safe execution."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

from modules.tools.base import BaseTool, ExecutionContext, ToolPermission, ToolResult

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger

logger = logging.getLogger("aru.tools.manager")


class ToolManager:
    """
    Central registry and execution manager for all Aru AI tools.
    Enforces MCP architecture, schema validation, permission checks, and structured logging.
    """

    def __init__(self, activity: ActivityLogger | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self.activity = activity

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if not isinstance(tool, BaseTool):
            raise TypeError(f"Expected BaseTool instance, got {type(tool).__name__}")
        if not tool.name or not isinstance(tool.name, str):
            raise ValueError("Tool must define a non-empty string name")

        key = tool.name.strip().lower()
        self._tools[key] = tool
        logger.info("Tool registered: '%s' (perm=%s)", tool.name, tool.required_permission.value)
        if self.activity:
            self.activity.log("tool_registry", "register", f"tool={tool.name} perm={tool.required_permission.value}")

    def unregister_tool(self, name: str) -> bool:
        """Unregister a tool by name."""
        key = name.strip().lower()
        if key in self._tools:
            del self._tools[key]
            logger.info("Tool unregistered: '%s'", name)
            return True
        return False

    def get_tool(self, name: str) -> BaseTool | None:
        """Retrieve a tool by name (case-insensitive)."""
        return self._tools.get(name.strip().lower())

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name.strip().lower() in self._tools

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP-style schemas for all registered tools."""
        return [tool.to_mcp_schema() for tool in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """Return list of registered tool names."""
        return list(self._tools.keys())

    def check_permission(
        self,
        tool: BaseTool,
        context: ExecutionContext,
        action: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Verify whether the execution context has permission to run the tool.
        Supports action-level permission elevation (e.g., delete actions require ADMIN).
        """
        # Determine required permission level
        required = tool.required_permission
        if action:
            act = action.strip().lower()
            if act in ("delete", "remove", "drop", "destroy"):
                required = ToolPermission.ADMIN
            elif act in ("save", "add", "write", "update", "create", "modify", "patch"):
                if required.level < ToolPermission.WRITE.level:
                    required = ToolPermission.WRITE

        if context.has_permission(required):
            return True, None

        return False, (
            f"Permission denied: Tool '{tool.name}' requires '{required.value}' permission. "
            f"Caller '{context.caller}' (user_id={context.user_id}, boss={context.is_boss}) lacks authorization."
        )

    async def execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """
        Safely execute a registered tool by name with arguments and execution context.
        Performs discovery, permission verification, schema validation, and timeout handling.
        """
        start_time = time.perf_counter()
        tool = self.get_tool(name)
        if not tool:
            err = f"Tool '{name}' not found. Available tools: {', '.join(self.get_tool_names())}"
            logger.warning(err)
            return ToolResult(success=False, error=err, metadata={"tool": name})

        action = args.get("action") if isinstance(args.get("action"), str) else None

        # 1. Permission check
        permitted, perm_err = self.check_permission(tool, context, action=action)
        if not permitted:
            logger.warning(
                "Tool execution unauthorized | tool=%s user=%s boss=%s error=%s",
                name,
                context.user_id,
                context.is_boss,
                perm_err,
            )
            if self.activity:
                self.activity.log("tool_security", "denied", f"tool={name} user={context.user_id}")
            return ToolResult(
                success=False,
                error=perm_err,
                metadata={"tool": name, "reason": "unauthorized"},
            )

        # 2. Input validation
        valid, val_err = tool.validate_input(args)
        if not valid:
            logger.warning("Tool argument validation failed | tool=%s error=%s", name, val_err)
            return ToolResult(
                success=False,
                error=f"Invalid arguments for tool '{name}': {val_err}",
                metadata={"tool": name, "reason": "validation_failed"},
            )

        # 3. Execution with timeout & structured logging
        logger.info(
            "Executing tool | tool=%s action=%s user=%s caller=%s",
            name,
            action,
            context.user_id,
            context.caller,
        )

        try:
            result = await asyncio.wait_for(tool.execute(**args), timeout=tool.timeout)
        except asyncio.TimeoutError:
            duration = time.perf_counter() - start_time
            err_msg = f"Tool '{name}' execution timed out after {tool.timeout}s"
            logger.error("Tool timeout | tool=%s duration=%.2fs", name, duration)
            if self.activity:
                self.activity.log_error("tool", name, TimeoutError(err_msg))
            return ToolResult(
                success=False,
                error=err_msg,
                metadata={"tool": name, "duration_sec": duration, "timeout": True},
            )
        except Exception as exc:
            duration = time.perf_counter() - start_time
            err_msg = f"Tool '{name}' execution failed: {type(exc).__name__}: {exc}"
            logger.exception("Tool execution error | tool=%s duration=%.2fs error=%s", name, duration, exc)
            if self.activity:
                self.activity.log_error("tool", name, exc)
            return ToolResult(
                success=False,
                error=err_msg,
                metadata={"tool": name, "duration_sec": duration},
            )

        duration = time.perf_counter() - start_time
        result.metadata["duration_sec"] = round(duration, 4)
        result.metadata["tool"] = name

        logger.info(
            "Tool executed successfully | tool=%s success=%s duration=%.3fs",
            name,
            result.success,
            duration,
        )
        if self.activity:
            self.activity.log(
                "tool_execution",
                name,
                f"success={result.success} duration={duration:.3f}s",
            )

        return result
