"""Specialized Agents for Sprint 6 Multi-Agent Autonomous Automation.

Contains:
- SpecializedResearchAgent (ResearchAgent)
- SpecializedMemoryAgent (MemoryAgent)
- SpecializedBrowserAgent (BrowserAgent)
- SpecializedTaskAgent (TaskAgent)
- SpecializedSchedulerAgent (SchedulerAgent)
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from modules.multi_agent.base_agent import BaseSpecializedAgent
from modules.multi_agent.messages import AgentContext

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.multi_agent.event_bus import AgentEventBus
    from modules.tools.browser_tool import BrowserTool
    from modules.tools.memory_tool import MemoryTool
    from modules.tools.research_tool import ResearchTool
    from modules.tools.task_tool import TaskTool
    from modules.scheduler import AruScheduler

logger = logging.getLogger("aru.multi_agent.specialized")


class SpecializedResearchAgent(BaseSpecializedAgent):
    """Specialized agent for web queries, fact-checking, scraping, and source evaluation."""
    name = "research"
    role = "web_research"
    description = "Searches the live web, verifies citations, scrapes URLs, and validates job listings."

    def __init__(
        self,
        event_bus: AgentEventBus,
        research_tool: ResearchTool | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        super().__init__(event_bus, activity)
        self.tool = research_tool

    async def execute_task(
        self,
        task_description: str,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        context.cancellation_token.throw_if_cancelled()
        action = input_data.get("action", "search")
        query = input_data.get("query") or input_data.get("q") or task_description
        url = input_data.get("url")

        if self.tool is None:
            from modules.tools.research_tool import ResearchTool
            self.tool = ResearchTool(activity=self.activity)

        if action == "scrape" and url:
            res = await self.tool.execute(action="scrape", url=url)
        else:
            res = await self.tool.execute(action="search", query=query, max_results=input_data.get("max_results", 5))

        if not res.success:
            return {"success": False, "error": res.error, "output": None}

        # Store in context artifacts
        context.artifacts[f"research_{query[:20]}"] = res.output
        return {
            "success": True,
            "output": res.output,
            "metadata": res.metadata,
        }


class SpecializedMemoryAgent(BaseSpecializedAgent):
    """Specialized agent for FTS5 memory retrieval, fact indexing, and knowledge consolidation."""
    name = "memory"
    role = "persistent_memory"
    description = "Searches memories with BM25, stores long-term facts, and consolidates knowledge."

    def __init__(
        self,
        event_bus: AgentEventBus,
        memory_tool: MemoryTool | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        super().__init__(event_bus, activity)
        self.tool = memory_tool

    async def execute_task(
        self,
        task_description: str,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        context.cancellation_token.throw_if_cancelled()
        action = input_data.get("action", "search")
        query = input_data.get("query") or input_data.get("q") or task_description
        content = input_data.get("content") or input_data.get("fact")
        category = input_data.get("category", "fact")

        if self.tool is None:
            from modules.tools.memory_tool import MemoryTool
            self.tool = MemoryTool(activity=self.activity)

        if action == "save":
            res = await self.tool.execute(
                action="save",
                content=content or task_description,
                category=category,
                title=input_data.get("title", ""),
            )
        elif action == "list":
            res = await self.tool.execute(action="list", category=category)
        elif action == "delete":
            res = await self.tool.execute(action="delete", id=input_data.get("id"))
        else:
            res = await self.tool.execute(action="search", query=query, limit=input_data.get("limit", 5))

        return {
            "success": res.success,
            "output": res.output if res.success else None,
            "error": res.error if not res.success else None,
            "metadata": res.metadata,
        }


class SpecializedBrowserAgent(BaseSpecializedAgent):
    """Specialized agent for headless browser automation (Playwright)."""
    name = "browser"
    role = "browser_automation"
    description = "Navigates live websites, renders dynamic JS, extracts DOM text, and takes screenshots."

    def __init__(
        self,
        event_bus: AgentEventBus,
        browser_tool: BrowserTool | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        super().__init__(event_bus, activity)
        self.tool = browser_tool

    async def execute_task(
        self,
        task_description: str,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        context.cancellation_token.throw_if_cancelled()
        action = input_data.get("action", "navigate")
        url = input_data.get("url") or task_description

        if self.tool is None:
            from modules.tools.browser_tool import BrowserTool
            self.tool = BrowserTool(activity=self.activity)

        res = await self.tool.execute(
            action=action,
            url=url,
            selector=input_data.get("selector", "body"),
            full_page=input_data.get("full_page", False),
        )

        return {
            "success": res.success,
            "output": res.output if res.success else None,
            "error": res.error if not res.success else None,
            "metadata": res.metadata,
        }


class SpecializedTaskAgent(BaseSpecializedAgent):
    """Specialized agent for smart task lifecycle, prioritization, and follow-ups."""
    name = "task"
    role = "task_management"
    description = "Creates priority tasks, tracks deadlines, updates progress, and checks overdue items."

    def __init__(
        self,
        event_bus: AgentEventBus,
        task_tool: TaskTool | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        super().__init__(event_bus, activity)
        self.tool = task_tool

    async def execute_task(
        self,
        task_description: str,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        context.cancellation_token.throw_if_cancelled()
        action = input_data.get("action", "add")
        title = input_data.get("title") or task_description
        priority = input_data.get("priority", "medium")
        due_date = input_data.get("due_date")

        if self.tool is None:
            from modules.tools.task_tool import TaskTool
            self.tool = TaskTool(activity=self.activity)

        if action == "list":
            res = await self.tool.execute(
                action="list",
                status=input_data.get("status"),
                priority=input_data.get("priority"),
            )
        elif action == "update_status":
            res = await self.tool.execute(
                action="update_status",
                id=input_data.get("id"),
                status=input_data.get("status"),
            )
        elif action == "delete":
            res = await self.tool.execute(action="delete", id=input_data.get("id"))
        else:
            # Default action: add
            res = await self.tool.execute(
                action="add",
                title=title,
                description=input_data.get("description", ""),
                priority=priority,
                due_date=due_date,
            )

        return {
            "success": res.success,
            "output": res.output if res.success else None,
            "error": res.error if not res.success else None,
            "metadata": res.metadata,
        }


class SpecializedSchedulerAgent(BaseSpecializedAgent):
    """Specialized agent for reminders, background cron tasks, and maintenance scheduling."""
    name = "scheduler"
    role = "scheduling_and_reminders"
    description = "Schedules timed reminders, checks background jobs, and manages calendar crons."

    def __init__(
        self,
        event_bus: AgentEventBus,
        scheduler: AruScheduler | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        super().__init__(event_bus, activity)
        self.scheduler = scheduler

    async def execute_task(
        self,
        task_description: str,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        context.cancellation_token.throw_if_cancelled()
        action = input_data.get("action", "schedule_reminder")
        message = input_data.get("message") or task_description
        run_at_str = input_data.get("run_at")

        if not self.scheduler:
            return {
                "success": False,
                "error": "Scheduler service not configured",
                "output": None,
            }

        if action == "maintenance":
            summary = self.scheduler.run_maintenance_now()
            return {"success": True, "output": f"Maintenance finished: {summary}"}

        # Schedule reminder
        import uuid
        from datetime import datetime
        try:
            if run_at_str:
                dt = datetime.fromisoformat(run_at_str)
            else:
                # Default to tomorrow 9am if unspecified
                from datetime import timedelta
                dt = datetime.now() + timedelta(days=1)
                dt = dt.replace(hour=9, minute=0, second=0, microsecond=0)

            rid = f"agent_remind_{uuid.uuid4().hex[:6]}"
            ok = self.scheduler.schedule_reminder(rid, dt, message)
            return {
                "success": ok,
                "output": f"Reminder set for {dt.strftime('%Y-%m-%d %H:%M')}: {message}",
                "reminder_id": rid,
            }
        except Exception as exc:
            return {"success": False, "error": f"Failed to schedule reminder: {exc}"}
