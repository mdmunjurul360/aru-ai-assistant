"""Tool executor and sandboxed execution engine for ARU AI V4."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from aru.core.logging import StructuredLogger
from aru.tools.base import BaseTool
from aru.tools.models import ExecutionContext, ToolResult
from aru.tools.registry import ToolRegistry


class ToolExecutor:
    """
    Sandboxed runner enforcing permissions, parameter validation,
    execution timeouts, exception trapping, and audit logging.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._registry = registry
        self._logger = logger or StructuredLogger("aru.tools.executor")

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> ToolResult:
        """
        Execute a tool by name with safety checks and timeout isolation.
        """
        tool = self._registry.get(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' is not registered.",
                metadata={"reason": "not_found"},
            )

        # 1. Permission check
        ctx = context or ExecutionContext(user_id=0, is_boss=False)
        if not ctx.has_permission(tool.required_permission):
            self._logger.warning(
                "Permission denied for tool '%s': required %s, user_id=%d",
                tool.name,
                tool.required_permission.value,
                ctx.user_id,
            )
            return ToolResult(
                success=False,
                error=f"Permission denied: '{tool.name}' requires {tool.required_permission.value} permission.",
                metadata={"reason": "unauthorized", "required_permission": tool.required_permission.value},
            )

        # 2. Argument validation
        validation_errors = tool.validate_arguments(arguments)
        if validation_errors:
            return ToolResult(
                success=False,
                error=f"Invalid arguments for '{tool.name}': {'; '.join(validation_errors)}",
                metadata={"reason": "validation_error", "errors": validation_errors},
            )

        # 3. Sandboxed execution with timeout
        start = time.perf_counter()
        self._logger.info("Executing tool '%s' with timeout %.1fs", tool.name, tool.timeout)

        try:
            res = await asyncio.wait_for(
                tool.execute(**arguments),
                timeout=tool.timeout,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Attach duration to metadata
            meta = dict(res.metadata)
            meta["duration_ms"] = round(elapsed_ms, 2)

            return ToolResult(
                success=res.success,
                output=res.output,
                error=res.error,
                metadata=meta,
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._logger.error("Tool '%s' timed out after %.1fs", tool.name, tool.timeout)
            return ToolResult(
                success=False,
                error=f"Tool '{tool.name}' execution timed out after {tool.timeout} seconds.",
                metadata={"timeout": True, "duration_ms": round(elapsed_ms, 2)},
            )
        except Exception as err:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._logger.exception("Tool '%s' raised unhandled exception: %s", tool.name, err)
            return ToolResult(
                success=False,
                error=f"Tool execution failed: {err}",
                metadata={"exception": str(err), "duration_ms": round(elapsed_ms, 2)},
            )
