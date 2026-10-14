"""Unit tests for Phase 9: Planner."""

from __future__ import annotations

import pytest

from aru.planner import (
    CircularDependencyError,
    DependencyGraph,
    Goal,
    GoalDecomposer,
    Plan,
    PlanStep,
    ReActPlanner,
    ReActStep,
    Replanner,
    StepStatus,
)
from aru.tools import CalculatorTool, MemoryTool, ToolRegistry, WebSearchTool


def test_dependency_graph_topological_sort() -> None:
    """Verify DependencyGraph calculates execution order and catches cycles."""
    # S1 -> S2 -> S3
    s1 = PlanStep(id=1, title="Step 1", tool_name="tool_a", depends_on=[])
    s2 = PlanStep(id=2, title="Step 2", tool_name="tool_b", depends_on=[1])
    s3 = PlanStep(id=3, title="Step 3", tool_name="tool_c", depends_on=[2])

    order = DependencyGraph.validate_plan([s1, s2, s3])
    assert order == [1, 2, 3]

    # Branching: S1 -> S2, S1 -> S3, S2 & S3 -> S4
    s4 = PlanStep(id=4, title="Step 4", tool_name="tool_d", depends_on=[2, 3])
    s3.depends_on = [1]
    order_branch = DependencyGraph.validate_plan([s1, s2, s3, s4])
    assert order_branch[0] == 1
    assert order_branch[-1] == 4


def test_dependency_graph_cycle_detection() -> None:
    """Verify DependencyGraph raises CircularDependencyError on cycles."""
    s1 = PlanStep(id=1, title="Step 1", tool_name="tool_a", depends_on=[2])
    s2 = PlanStep(id=2, title="Step 2", tool_name="tool_b", depends_on=[1])

    with pytest.raises(CircularDependencyError):
        DependencyGraph.validate_plan([s1, s2])


def test_plan_runnable_steps_progression() -> None:
    """Verify Plan.get_runnable_steps unblocks steps as dependencies complete."""
    goal = Goal(description="Test goal")
    s1 = PlanStep(id=1, title="Fetch", tool_name="tool_a", depends_on=[])
    s2 = PlanStep(id=2, title="Process", tool_name="tool_b", depends_on=[1])
    plan = Plan(goal=goal, steps=[s1, s2])

    # Initially only S1 is runnable
    runnable = plan.get_runnable_steps()
    assert len(runnable) == 1
    assert runnable[0].id == 1

    # Mark S1 completed
    plan.mark_step_completed(1, result="Data")
    assert s1.status == StepStatus.COMPLETED

    # Now S2 becomes runnable
    runnable_next = plan.get_runnable_steps()
    assert len(runnable_next) == 1
    assert runnable_next[0].id == 2

    # Mark S2 completed
    plan.mark_step_completed(2, result="Finished")
    assert plan.is_completed is True


@pytest.mark.asyncio
async def test_goal_decomposer_patterns() -> None:
    """Verify GoalDecomposer decomposes different intents into valid plans."""
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(MemoryTool())
    registry.register(WebSearchTool())

    decomposer = GoalDecomposer(tool_registry=registry)

    # 1. Math intent
    math_goal = Goal(description="Calculate 25 * 4 + 10")
    plan_math = await decomposer.decompose(math_goal)
    assert len(plan_math.steps) == 1
    assert plan_math.steps[0].tool_name == "calculator"
    assert "25 * 4 + 10" in plan_math.steps[0].args["expression"]

    # 2. Memory intent
    mem_goal = Goal(description="Remember that Boss likes tea")
    plan_mem = await decomposer.decompose(mem_goal)
    assert len(plan_mem.steps) == 1
    assert plan_mem.steps[0].tool_name == "memory"
    assert plan_mem.steps[0].args["action"] == "save"

    # 3. Web search intent
    search_goal = Goal(description="Search the web for Python 3.12")
    plan_search = await decomposer.decompose(search_goal)
    assert len(plan_search.steps) == 1
    assert plan_search.steps[0].tool_name == "web_search"


def test_react_planner_parsing() -> None:
    """Verify ReActPlanner parses Thought, Action, Action Input, and Final Answer."""
    planner = ReActPlanner()

    # Step with tool action
    text_action = (
        "Thought: I need to calculate the value.\n"
        "Action: calculator\n"
        "Action Input: {\"expression\": \"5 * 10\"}"
    )
    thought, tool, args, final_ans = planner.parse_action_response(text_action)
    assert "calculate the value" in thought
    assert tool == "calculator"
    assert args == {"expression": "5 * 10"}
    assert final_ans is None

    # Step with final answer
    text_final = (
        "Thought: The calculation is complete.\n"
        "Final Answer: The total is 50."
    )
    thought2, tool2, args2, final_ans2 = planner.parse_action_response(text_final)
    assert tool2 is None
    assert final_ans2 == "The total is 50."


def test_replanner_retry_and_fallback() -> None:
    """Verify Replanner retries steps and inserts fallback steps with dependency re-routing."""
    goal = Goal(description="Fallback test")
    s1 = PlanStep(id=1, title="Primary search", tool_name="web_search", depends_on=[], max_retries=1)
    s2 = PlanStep(id=2, title="Process search", tool_name="calculator", depends_on=[1])
    plan = Plan(goal=goal, steps=[s1, s2])

    # 1. Retry test
    plan.mark_step_failed(1, error="Network failure")
    retried = Replanner.retry_step(plan, 1)
    assert retried is not None
    assert retried.status == StepStatus.PENDING
    assert retried.retry_count == 1

    # Retry limit reached
    plan.mark_step_failed(1, error="Network failure 2")
    assert Replanner.retry_step(plan, 1) is None

    # 2. Fallback insertion
    fallback = Replanner.insert_fallback_step(
        plan=plan,
        failed_step_id=1,
        fallback_tool="memory",
        fallback_args={"action": "recall", "query": "cached query"},
        fallback_title="Cached Memory Fallback",
    )
    assert fallback.id == 3
    assert fallback.tool_name == "memory"
    assert s1.status == StepStatus.SKIPPED
    # Step 2 should now depend on Step 3 (fallback) instead of Step 1
    assert s2.depends_on == [3]
