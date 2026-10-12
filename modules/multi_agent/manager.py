"""AgentManager: Central coordinator for the Multi-Agent Autonomous Automation System."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from modules.multi_agent.base_agent import BaseSpecializedAgent
from modules.multi_agent.event_bus import AgentEventBus
from modules.multi_agent.messages import AgentContext, PlanResult
from modules.multi_agent.planner_agent import PlannerAgent
from modules.multi_agent.specialized_agents import (
    SpecializedBrowserAgent,
    SpecializedMemoryAgent,
    SpecializedResearchAgent,
    SpecializedSchedulerAgent,
    SpecializedTaskAgent,
)
from modules.multi_agent.workflows import (
    BaseWorkflow,
    JobMonitoringWorkflow,
    MemoryConsolidationWorkflow,
    MorningBriefingWorkflow,
    ReminderExecutionWorkflow,
    ResearchUpdateWorkflow,
    TaskFollowUpWorkflow,
)

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.ai import AruAI
    from modules.scheduler import AruScheduler
    from modules.tools.manager import ToolManager

logger = logging.getLogger("aru.multi_agent.manager")


class MultiAgentManager:
    """
    Central orchestration hub for Aru AI's multi-agent system.
    Coordinates PlannerAgent, specialized agents, EventBus messaging,
    and background autonomous workflows.
    """

    def __init__(
        self,
        ai: "AruAI",
        tool_manager: "ToolManager",
        scheduler: "AruScheduler | None" = None,
        activity: "ActivityLogger | None" = None,
    ) -> None:
        self.ai = ai
        self.tool_manager = tool_manager
        self.scheduler = scheduler
        self.activity = activity

        self.event_bus = AgentEventBus()
        self._agents: dict[str, BaseSpecializedAgent] = {}
        self._workflows: dict[str, BaseWorkflow] = {}

        self._initialize_default_agents()
        self._initialize_default_workflows()

    def _initialize_default_agents(self) -> None:
        """Register the 6 core specialized agents."""
        # 1. Specialized Tools mapping
        browser_tool = self.tool_manager.get_tool("browser")
        mem_tool = self.tool_manager.get_tool("memory")
        res_tool = self.tool_manager.get_tool("research")
        task_tool = self.tool_manager.get_tool("tasks")

        # 2. Specialized Agents
        research_agent = SpecializedResearchAgent(self.event_bus, research_tool=res_tool, activity=self.activity)  # type: ignore
        memory_agent = SpecializedMemoryAgent(self.event_bus, memory_tool=mem_tool, activity=self.activity)  # type: ignore
        browser_agent = SpecializedBrowserAgent(self.event_bus, browser_tool=browser_tool, activity=self.activity)  # type: ignore
        task_agent = SpecializedTaskAgent(self.event_bus, task_tool=task_tool, activity=self.activity)  # type: ignore
        scheduler_agent = SpecializedSchedulerAgent(self.event_bus, scheduler=self.scheduler, activity=self.activity)

        # 3. Planner Agent
        planner_agent = PlannerAgent(self.event_bus, ai=self.ai, activity=self.activity)

        for ag in (research_agent, memory_agent, browser_agent, task_agent, scheduler_agent, planner_agent):
            self.register_agent(ag)

    def _initialize_default_workflows(self) -> None:
        """Register the 6 background autonomous workflows."""
        for wf_cls in (
            MorningBriefingWorkflow,
            ResearchUpdateWorkflow,
            JobMonitoringWorkflow,
            ReminderExecutionWorkflow,
            TaskFollowUpWorkflow,
            MemoryConsolidationWorkflow,
        ):
            wf = wf_cls(self)
            self._workflows[wf.name] = wf

    def register_agent(self, agent: BaseSpecializedAgent) -> None:
        """Register and start an agent."""
        key = agent.name.strip().lower()
        agent.start()
        self._agents[key] = agent
        logger.info("Agent registered with manager: '%s' (%s)", agent.name, agent.role)

    def get_agent(self, name: str) -> BaseSpecializedAgent | None:
        return self._agents.get(name.strip().lower())

    def list_agents(self) -> list[dict[str, Any]]:
        """List all active specialized agents."""
        return [
            {
                "name": a.name,
                "role": a.role,
                "description": a.description,
            }
            for a in self._agents.values()
        ]

    def list_workflows(self) -> list[dict[str, Any]]:
        """List registered background workflows."""
        return [
            {
                "name": w.name,
                "description": w.description,
            }
            for w in self._workflows.values()
        ]

    async def execute_goal(
        self,
        goal: str,
        *,
        context: AgentContext | None = None,
    ) -> PlanResult:
        """
        Execute high-level goal using the PlannerAgent to decompose,
        delegate via the EventBus, and synthesize the result.
        """
        planner = self.get_agent("planner")
        if not isinstance(planner, PlannerAgent):
            raise RuntimeError("PlannerAgent is not registered")

        ctx = context or AgentContext()
        return await planner.plan_and_execute(goal, context=ctx)

    async def run_workflow(
        self,
        name: str,
        *,
        context: AgentContext | None = None,
    ) -> dict[str, Any]:
        """Trigger an autonomous background workflow by name."""
        key = name.strip().lower()
        wf = self._workflows.get(key)
        if not wf:
            return {"success": False, "error": f"Workflow '{name}' not found"}

        return await wf.run(context=context)

    def get_status(self) -> dict[str, Any]:
        """System health and multi-agent metrics."""
        return {
            "agents_count": len(self._agents),
            "agents": list(self._agents.keys()),
            "workflows_count": len(self._workflows),
            "workflows": list(self._workflows.keys()),
            "event_bus_history_len": len(self.event_bus.get_event_history()),
        }

    def shutdown(self) -> None:
        """Stop all agents cleanly."""
        for agent in self._agents.values():
            agent.stop()
        self.event_bus.clear_history()
        logger.info("MultiAgentManager shutdown completed")


# Type alias for requirement compatibility
AgentManager = MultiAgentManager
