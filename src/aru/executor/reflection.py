"""Reflection loop analyzing execution outcomes for ARU AI V4 Executor."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict
from aru.planner.models import PlanStep
from aru.tools.models import ToolResult


class ReflectionResult(BaseModel):
    """Assessment produced by the ReflectionEngine after step completion."""

    model_config = ConfigDict(frozen=True)

    success: bool
    feedback: str
    needs_replanning: bool = False


class ReflectionEngine:
    """
    Evaluates raw tool execution output against the expected step objective,
    detecting subtle semantic errors or incomplete results.
    """

    @classmethod
    def evaluate(cls, step: PlanStep, tool_result: ToolResult) -> ReflectionResult:
        """Analyze tool result and determine outcome quality."""
        # 1. Obvious execution failure
        if not tool_result.success:
            return ReflectionResult(
                success=False,
                feedback=f"Tool '{step.tool_name}' failed with error: {tool_result.error}",
                needs_replanning=True,
            )

        # 2. Check for empty or invalid output where content is expected
        out = tool_result.output
        if out is None:
            return ReflectionResult(
                success=True,
                feedback=f"Step '{step.title}' completed with empty output.",
                needs_replanning=False,
            )

        # String output analysis
        if isinstance(out, str):
            lower_out = out.lower()
            if "error:" in lower_out or "failed:" in lower_out or "exception:" in lower_out:
                return ReflectionResult(
                    success=False,
                    feedback=f"Tool output contains error indicators: {out}",
                    needs_replanning=True,
                )

        # Successful reflection
        return ReflectionResult(
            success=True,
            feedback=f"Step '{step.title}' fulfilled successfully.",
            needs_replanning=False,
        )
