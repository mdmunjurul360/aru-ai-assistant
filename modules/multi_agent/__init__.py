"""Aru AI Multi-Agent Autonomous Automation System.

Sprint 6 Architecture:
Coordinates specialized agents (PlannerAgent, ResearchAgent, MemoryAgent, BrowserAgent,
TaskAgent, SchedulerAgent) over an asynchronous AgentEventBus with execution tracing,
retries, timeout handling, cooperative cancellation, and autonomous background workflows.
"""

from __future__ import annotations

from modules.multi_agent.base_agent import BaseSpecializedAgent
from modules.multi_agent.event_bus import (
    AgentEventBus,
    CancellationToken,
    EventTraceRecord,
)
from modules.multi_agent.manager import AgentManager, MultiAgentManager
from modules.multi_agent.messages import (
    AgentContext,
    AgentMessage,
    MessageType,
    PlanResult,
    SubTask,
)
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

# Aliases matching Sprint 6 requirements specification
ResearchAgent = SpecializedResearchAgent
MemoryAgent = SpecializedMemoryAgent
BrowserAgent = SpecializedBrowserAgent
TaskAgent = SpecializedTaskAgent
SchedulerAgent = SpecializedSchedulerAgent

__all__ = [
    # Event Bus & Cancellation
    "AgentEventBus",
    "CancellationToken",
    "EventTraceRecord",
    # Messages & Context
    "MessageType",
    "AgentMessage",
    "AgentContext",
    "SubTask",
    "PlanResult",
    # Agents
    "BaseSpecializedAgent",
    "PlannerAgent",
    "SpecializedResearchAgent",
    "SpecializedMemoryAgent",
    "SpecializedBrowserAgent",
    "SpecializedTaskAgent",
    "SpecializedSchedulerAgent",
    "ResearchAgent",
    "MemoryAgent",
    "BrowserAgent",
    "TaskAgent",
    "SchedulerAgent",
    # Manager
    "MultiAgentManager",
    "AgentManager",
    # Workflows
    "BaseWorkflow",
    "MorningBriefingWorkflow",
    "ResearchUpdateWorkflow",
    "JobMonitoringWorkflow",
    "ReminderExecutionWorkflow",
    "TaskFollowUpWorkflow",
    "MemoryConsolidationWorkflow",
]
