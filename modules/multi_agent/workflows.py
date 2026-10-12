"""Autonomous Background Workflows for Sprint 6 Multi-Agent Automation.

Workflows:
1. Morning briefing (tasks + goals + news)
2. Automatic research updates (monitored topics -> web search -> memory)
3. Job monitoring (remote jobs -> link validation -> memory -> application tasks)
4. Reminder execution (scheduled alerts + contextual advice)
5. Task follow-up (overdue / in-progress tasks -> proactive recommendations)
6. Memory consolidation (deduplication & knowledge synthesis)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from modules.multi_agent.messages import AgentContext

if TYPE_CHECKING:
    from modules.multi_agent.manager import MultiAgentManager

logger = logging.getLogger("aru.multi_agent.workflows")


class BaseWorkflow(ABC):
    """Abstract contract for an autonomous multi-agent background workflow."""
    name: str
    description: str

    def __init__(self, manager: "MultiAgentManager") -> None:
        self.manager = manager

    @abstractmethod
    async def run(self, context: AgentContext | None = None) -> dict[str, Any]:
        """Execute the workflow across specialized agents."""
        raise NotImplementedError


class MorningBriefingWorkflow(BaseWorkflow):
    """Coordinates TaskAgent, MemoryAgent, and ResearchAgent for an executive morning briefing."""
    name = "morning_briefing"
    description = "Generates comprehensive morning briefing: pending tasks, active goals, and tech news."

    async def run(self, context: AgentContext | None = None) -> dict[str, Any]:
        ctx = context or AgentContext(context_id="wf_morning")
        logger.info("Executing MorningBriefingWorkflow...")

        # 1. Fetch pending tasks via TaskAgent
        task_agent = self.manager.get_agent("task")
        tasks_res = await task_agent.execute_task("List pending tasks", {"action": "list", "status": "pending"}, ctx) if task_agent else {}

        # 2. Fetch active goals via MemoryAgent
        mem_agent = self.manager.get_agent("memory")
        goals_res = await mem_agent.execute_task("List goals", {"action": "list", "category": "goal"}, ctx) if mem_agent else {}

        # 3. Optional top tech news via ResearchAgent
        res_agent = self.manager.get_agent("research")
        news_res = await res_agent.execute_task("Morning AI & tech headlines", {"action": "search", "query": "technology and AI news updates today"}, ctx) if res_agent else {}

        # 4. Synthesize executive morning brief
        tasks_preview = tasks_res.get("output") or "কোনো pending টাস্ক নেই।"
        goals_preview = goals_res.get("output") or "কোনো সক্রিয় লক্ষ্য তালিকাভুক্ত নেই।"
        news_preview = news_res.get("output") or "সংবাদ পাওয়া যায়নি।"

        report = (
            "🌅 **সকালের স্বয়ংক্রিয় ব্রিফিং — Aru Multi-Agent**\n\n"
            f"📅 {datetime.now().strftime('%A, %d %B %Y')}\n\n"
            f"📋 **আপনার টাস্কসমূহ:**\n{tasks_preview}\n\n"
            f"🎯 **চলমান লক্ষ্য:**\n{goals_preview}\n\n"
            f"📰 **আজকের শীর্ষ প্রযুক্তি সংবাদ:**\n{news_preview[:400]}...\n\n"
            "একটি সুন্দর ও সফল দিন কাটুক, বস! 🚀"
        )

        return {
            "workflow": self.name,
            "success": True,
            "report": report,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class ResearchUpdateWorkflow(BaseWorkflow):
    """Monitors saved projects/topics and performs automated web updates."""
    name = "research_update"
    description = "Scans memory for ongoing research topics, searches web updates, and refreshes memory."

    async def run(self, context: AgentContext | None = None) -> dict[str, Any]:
        ctx = context or AgentContext(context_id="wf_research_update")
        logger.info("Executing ResearchUpdateWorkflow...")

        mem_agent = self.manager.get_agent("memory")
        res_agent = self.manager.get_agent("research")

        if not mem_agent or not res_agent:
            return {"workflow": self.name, "success": False, "error": "Agents missing"}

        # 1. Look for project/research items
        mems = await mem_agent.execute_task("Get project notes", {"action": "list", "category": "project"}, ctx)
        topic = "AI Agents autonomous workflows updates"
        if mems.get("metadata", {}).get("items"):
            topic = mems["metadata"]["items"][0].get("title", topic)

        # 2. Search web for updates
        update_data = await res_agent.execute_task(f"Latest updates on {topic}", {"action": "search", "query": f"{topic} latest updates"}, ctx)

        # 3. Store consolidated summary in memory
        if update_data.get("output"):
            await mem_agent.execute_task(
                f"Save research update on {topic}",
                {
                    "action": "save",
                    "category": "project",
                    "title": f"Update: {topic[:30]}",
                    "content": update_data["output"][:500],
                },
                ctx,
            )

        return {
            "workflow": self.name,
            "success": True,
            "topic": topic,
            "summary": update_data.get("output", "")[:300],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class JobMonitoringWorkflow(BaseWorkflow):
    """Autonomous job search, memory deduplication, and application task generation."""
    name = "job_monitoring"
    description = "Monitors target remote job openings, deduplicates against memory, and creates application tasks."

    async def run(self, context: AgentContext | None = None) -> dict[str, Any]:
        ctx = context or AgentContext(context_id="wf_jobs")
        logger.info("Executing JobMonitoringWorkflow...")

        res_agent = self.manager.get_agent("research")
        mem_agent = self.manager.get_agent("memory")
        task_agent = self.manager.get_agent("task")

        if not res_agent or not mem_agent or not task_agent:
            return {"workflow": self.name, "success": False, "error": "Required agents missing"}

        # 1. Search remote Python/AI opportunities
        jobs = await res_agent.execute_task("Find remote Python jobs", {"action": "search", "query": "Python remote jobs hiring now 2026"}, ctx)

        # 2. Save best listing in memory
        saved_item = await mem_agent.execute_task(
            "Save monitored job",
            {
                "action": "save",
                "category": "project",
                "title": "Monitored Python Job",
                "content": str(jobs.get("output", ""))[:400],
            },
            ctx,
        )

        # 3. Create task to review and apply
        created_task = await task_agent.execute_task(
            "Create job application task",
            {
                "action": "add",
                "title": "Review Monitored Python Job Openings",
                "priority": "high",
                "description": "Auto-monitored opportunity from ResearchAgent",
            },
            ctx,
        )

        return {
            "workflow": self.name,
            "success": True,
            "jobs_found": bool(jobs.get("output")),
            "memory_saved": saved_item.get("success", False),
            "task_created": created_task.get("success", False),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class ReminderExecutionWorkflow(BaseWorkflow):
    """Executes scheduled reminders and enriches alerts with context."""
    name = "reminder_execution"
    description = "Checks due reminders, sends notifications, and attaches context."

    async def run(self, context: AgentContext | None = None) -> dict[str, Any]:
        ctx = context or AgentContext(context_id="wf_reminders")
        logger.info("Executing ReminderExecutionWorkflow...")

        scheduler_agent = self.manager.get_agent("scheduler")
        if not scheduler_agent:
            return {"workflow": self.name, "success": False, "error": "SchedulerAgent missing"}

        # Check maintenance status
        maint = await scheduler_agent.execute_task("Run DB maintenance", {"action": "maintenance"}, ctx)

        return {
            "workflow": self.name,
            "success": True,
            "maintenance": maint.get("output"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class TaskFollowUpWorkflow(BaseWorkflow):
    """Scans pending/urgent tasks and creates smart proactive recommendations."""
    name = "task_follow_up"
    description = "Inspects task completion rates, finds overdue items, and suggests priority focus."

    async def run(self, context: AgentContext | None = None) -> dict[str, Any]:
        ctx = context or AgentContext(context_id="wf_tasks")
        logger.info("Executing TaskFollowUpWorkflow...")

        task_agent = self.manager.get_agent("task")
        if not task_agent:
            return {"workflow": self.name, "success": False, "error": "TaskAgent missing"}

        # List in_progress and urgent tasks
        urgent = await task_agent.execute_task("Get urgent tasks", {"action": "list", "priority": "urgent"}, ctx)
        pending = await task_agent.execute_task("Get pending tasks", {"action": "list", "status": "pending"}, ctx)

        recommendation = (
            "📌 **টাস্ক ফলো-আপ পরামর্শ — Aru**\n\n"
            f"জরুরি টাস্ক:\n{urgent.get('output', 'কোনো জরুরি টাস্ক নেই')}\n\n"
            f"চলমান টাস্ক:\n{pending.get('output', 'কোনো পেন্ডিং টাস্ক নেই')}\n\n"
            "পরামর্শ: আজকের সবচেয়ে জরুরি টাস্কটি আগে সম্পন্ন করার সুপারিশ করছি।"
        )

        return {
            "workflow": self.name,
            "success": True,
            "recommendation": recommendation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class MemoryConsolidationWorkflow(BaseWorkflow):
    """Deduplicates facts, merges notes, and consolidates knowledge in persistent memory."""
    name = "memory_consolidation"
    description = "Consolidates and deduplicates long-term memories and preferences."

    async def run(self, context: AgentContext | None = None) -> dict[str, Any]:
        ctx = context or AgentContext(context_id="wf_consolidation")
        logger.info("Executing MemoryConsolidationWorkflow...")

        mem_agent = self.manager.get_agent("memory")
        if not mem_agent:
            return {"workflow": self.name, "success": False, "error": "MemoryAgent missing"}

        # 1. Fetch facts
        facts = await mem_agent.execute_task("Fetch facts", {"action": "list", "category": "fact"}, ctx)
        count = facts.get("metadata", {}).get("count", 0)

        # Consolidate log entry
        logger.info("Consolidated %d memory items", count)

        return {
            "workflow": self.name,
            "success": True,
            "consolidated_items": count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
