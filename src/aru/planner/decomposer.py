"""Goal decomposition and plan generation for ARU AI V4 Planner."""

from __future__ import annotations

import re
from typing import Any
from aru.brain.interfaces import ILLMProvider
from aru.brain.models import LLMMessage
from aru.brain.router import LLMRouter
from aru.planner.graph import DependencyGraph
from aru.planner.models import Goal, Plan, PlanStep, StepStatus
from aru.tools.registry import ToolRegistry


class GoalDecomposer:
    """
    Decomposes user goals into structured, dependency-aware execution plans
    using semantic rules and optional LLM assistance.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        router: LLMRouter | None = None,
    ) -> None:
        self._registry = tool_registry or ToolRegistry()
        self._router = router

    async def decompose(self, goal: Goal) -> Plan:
        """Analyze a goal and construct a validated Plan."""
        desc = goal.description.strip().lower()

        # 1. Check for simple math calculation intent
        math_match = re.search(r"(?:calculate|compute|what is)\s+([0-9\+\-\*\/\^\(\)\.\s\%]+)", desc)
        if math_match and self._registry.has("calculator"):
            steps = [
                PlanStep(
                    id=1,
                    title="Compute mathematical expression",
                    tool_name="calculator",
                    args={"expression": math_match.group(1).strip()},
                    depends_on=[],
                )
            ]
            plan = Plan(goal=goal, steps=steps)
            DependencyGraph.validate_plan(plan.steps)
            return plan

        # 2. Check for memory intent
        if ("remember" in desc or "save memory" in desc) and self._registry.has("memory"):
            steps = [
                PlanStep(
                    id=1,
                    title="Persist memory fact",
                    tool_name="memory",
                    args={"action": "save", "content": goal.description},
                    depends_on=[],
                )
            ]
            plan = Plan(goal=goal, steps=steps)
            DependencyGraph.validate_plan(plan.steps)
            return plan

        if ("recall" in desc or "what did i say" in desc or "search memory" in desc) and self._registry.has("memory"):
            steps = [
                PlanStep(
                    id=1,
                    title="Search memory store",
                    tool_name="memory",
                    args={"action": "search", "query": goal.description},
                    depends_on=[],
                )
            ]
            plan = Plan(goal=goal, steps=steps)
            DependencyGraph.validate_plan(plan.steps)
            return plan

        # 3. Check for web search intent
        if ("search the web" in desc or "google" in desc or "look up" in desc) and self._registry.has("web_search"):
            query = re.sub(r"^(?:search the web for|look up|search for)\s+", "", desc, flags=re.IGNORECASE)
            steps = [
                PlanStep(
                    id=1,
                    title="Perform web search",
                    tool_name="web_search",
                    args={"query": query},
                    depends_on=[],
                )
            ]
            plan = Plan(goal=goal, steps=steps)
            DependencyGraph.validate_plan(plan.steps)
            return plan

        # 4. Multi-step Research & Calculate compound pattern:
        # e.g., "Find weather data and compute average"
        if "and calculate" in desc and self._registry.has("web_search") and self._registry.has("calculator"):
            parts = desc.split("and calculate")
            steps = [
                PlanStep(
                    id=1,
                    title=f"Gather data: {parts[0].strip()}",
                    tool_name="web_search",
                    args={"query": parts[0].strip()},
                    depends_on=[],
                ),
                PlanStep(
                    id=2,
                    title="Compute calculation from data",
                    tool_name="calculator",
                    args={"expression": "1 + 1"},  # Upstream piped in executor
                    depends_on=[1],
                ),
            ]
            plan = Plan(goal=goal, steps=steps)
            DependencyGraph.validate_plan(plan.steps)
            return plan

        # 5. Default single-step general action
        default_tool = "calculator" if self._registry.has("calculator") else "memory"
        steps = [
            PlanStep(
                id=1,
                title=f"Execute: {goal.description}",
                tool_name=default_tool,
                args={"query": goal.description} if default_tool == "memory" else {"expression": "0"},
                depends_on=[],
            )
        ]
        plan = Plan(goal=goal, steps=steps)
        DependencyGraph.validate_plan(plan.steps)
        return plan
