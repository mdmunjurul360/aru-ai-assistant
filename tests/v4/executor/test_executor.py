"""Unit tests for Phase 10: Executor."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from aru.executor import (
    ExecutionHistory,
    ExecutionState,
    PlanExecutor,
    ReflectionEngine,
)
from aru.planner.models import Goal, Plan, PlanStep, StepStatus
from aru.tools import CalculatorTool, ExecutionContext, ToolExecutor, ToolRegistry, ToolResult


@pytest.fixture
def test_tool_executor() -> ToolExecutor:
    """Provide a ToolExecutor with CalculatorTool registered."""
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    return ToolExecutor(registry)


@pytest.mark.asyncio
async def test_executor_successful_plan(test_tool_executor: ToolExecutor) -> None:
    """Verify PlanExecutor executes sequential steps and pipes output."""
    goal = Goal(description="Calculate multi-step math")
    s1 = PlanStep(id=1, title="Step 1", tool_name="calculator", args={"expression": "10 * 5"}, depends_on=[])
    s2 = PlanStep(id=2, title="Step 2", tool_name="calculator", args={"expression": "{step_1_output} + 25"}, depends_on=[1])

    plan = Plan(goal=goal, steps=[s1, s2])
    executor = PlanExecutor(tool_executor=test_tool_executor)

    history = await executor.execute_plan(plan, context=ExecutionContext(user_id=1, is_boss=True))

    assert history.state == ExecutionState.COMPLETED
    assert plan.is_completed is True
    assert s1.result == 50.0
    assert s2.result == 75.0
    assert history.final_output == 75.0
    assert len(history.records) == 2


@pytest.mark.asyncio
async def test_executor_max_iteration_guard(test_tool_executor: ToolExecutor) -> None:
    """Verify PlanExecutor terminates when exceeding max iterations."""
    goal = Goal(description="Loop test")
    # Step that fails and triggers endless retries if unbounded
    s1 = PlanStep(id=1, title="Always fail", tool_name="calculator", args={"expression": "bad_math()"}, depends_on=[], max_retries=100)

    plan = Plan(goal=goal, steps=[s1])
    # Set tight iteration limit
    executor = PlanExecutor(tool_executor=test_tool_executor, max_iterations=3, enable_replanning=False)

    history = await executor.execute_plan(plan, context=ExecutionContext(user_id=1, is_boss=True))

    assert history.state == ExecutionState.FAILED
    assert "iteration cap" in history.error
    assert history.iteration_count >= 3


@pytest.mark.asyncio
async def test_executor_timeout_guard(test_tool_executor: ToolExecutor) -> None:
    """Verify PlanExecutor aborts plan if overall timeout is exceeded."""
    goal = Goal(description="Timeout test")

    # Mock tool executor to sleep
    mock_tool_exec = MagicMock()
    async def slow_exec(*args, **kwargs):
        await asyncio.sleep(0.5)
        return ToolResult(success=True, output=42)

    mock_tool_exec.execute = AsyncMock(side_effect=slow_exec)

    s1 = PlanStep(id=1, title="Slow step 1", tool_name="slow", depends_on=[])
    s2 = PlanStep(id=2, title="Slow step 2", tool_name="slow", depends_on=[1])
    plan = Plan(goal=goal, steps=[s1, s2])

    executor = PlanExecutor(tool_executor=mock_tool_exec, timeout_seconds=0.2)
    history = await executor.execute_plan(plan)

    assert history.state == ExecutionState.FAILED
    assert "timeout" in history.error


@pytest.mark.asyncio
async def test_executor_retry_and_recovery(test_tool_executor: ToolExecutor) -> None:
    """Verify step succeeds after a transient failure via retry logic."""
    goal = Goal(description="Retry test")

    call_count = 0
    mock_tool_exec = MagicMock()

    async def flaky_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ToolResult(success=False, error="Temporary glitch")
        return ToolResult(success=True, output="Recovered")

    mock_tool_exec.execute = AsyncMock(side_effect=flaky_exec)

    s1 = PlanStep(id=1, title="Flaky step", tool_name="flaky", depends_on=[], max_retries=2)
    plan = Plan(goal=goal, steps=[s1])

    executor = PlanExecutor(tool_executor=mock_tool_exec, enable_replanning=False)
    history = await executor.execute_plan(plan)

    assert history.state == ExecutionState.COMPLETED
    assert plan.is_completed is True
    assert s1.result == "Recovered"
    assert s1.retry_count == 1
    assert len(history.records) == 2  # 1 failure record + 1 success record


@pytest.mark.asyncio
async def test_reflection_engine_evaluation() -> None:
    """Verify ReflectionEngine flags errors and accepts valid results."""
    step = PlanStep(id=1, title="Test step", tool_name="test")

    ok_res = ToolResult(success=True, output={"status": "all good"})
    ref_ok = ReflectionEngine.evaluate(step, ok_res)
    assert ref_ok.success is True
    assert ref_ok.needs_replanning is False

    err_res = ToolResult(success=False, error="Fatal database failure")
    ref_err = ReflectionEngine.evaluate(step, err_res)
    assert ref_err.success is False
    assert ref_err.needs_replanning is True
