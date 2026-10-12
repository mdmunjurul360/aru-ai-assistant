"""PlannerAgent: Decomposes complex user goals into DAG subtasks and coordinates specialized agents."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, TYPE_CHECKING

from modules.multi_agent.base_agent import BaseSpecializedAgent
from modules.multi_agent.messages import (
    AgentContext,
    AgentMessage,
    MessageType,
    PlanResult,
    SubTask,
)

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.ai import AruAI
    from modules.multi_agent.event_bus import AgentEventBus

logger = logging.getLogger("aru.multi_agent.planner")

PLANNER_SYSTEM_PROMPT = """You are the Lead Planning Agent for Aru AI's multi-agent autonomous system.
Your job is to break down the user's high-level goal into an efficient, ordered list of subtasks.
Each subtask must be delegated to exactly one of the available specialized agents:
- 'research': For live web searches, fact-checking, and URL scraping.
- 'memory': For searching FTS5 memories, saving persistent facts, or reading stored preferences.
- 'browser': For navigating live websites, rendering JavaScript, and capturing screenshots.
- 'task': For creating smart tasks, listing tasks, or updating priorities/statuses.
- 'scheduler': For scheduling reminders, cron maintenance, and time-based triggers.

Instructions:
1. Decompose the goal into 1 to 5 sequential or dependent subtasks.
2. For each subtask, specify:
   - id: unique string like "step_1", "step_2"
   - description: clear, actionable objective
   - agent: "research", "memory", "browser", "task", or "scheduler"
   - dependencies: list of prerequisite step IDs (e.g., ["step_1"])
   - input: JSON dictionary of parameters for the specialized agent.
3. If a step depends on the output of a prior step, you may reference it using `{{step_id.result}}`.
4. Output MUST be a valid JSON object matching:
{
  "subtasks": [
    {
      "id": "step_1",
      "description": "...",
      "agent": "...",
      "dependencies": [],
      "input": {...}
    }
  ]
}
"""


class PlannerAgent(BaseSpecializedAgent):
    """
    Orchestrating planner agent.
    Breaks down complex goals, creates execution plans, delegates subtasks via EventBus,
    and synthesizes final answers.
    """

    name = "planner"
    role = "orchestration_and_planning"
    description = "Decomposes complex goals into DAG subtasks and delegates to specialized agents."

    def __init__(
        self,
        event_bus: AgentEventBus,
        ai: AruAI,
        activity: ActivityLogger | None = None,
        max_subtasks: int = 8,
    ) -> None:
        super().__init__(event_bus, activity)
        self.ai = ai
        self.max_subtasks = max_subtasks

    async def execute_task(
        self,
        task_description: str,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        """Entry point if Planner is invoked as a subtask."""
        plan_result = await self.plan_and_execute(task_description, context=context)
        return plan_result.to_dict()

    async def decompose_goal(self, goal: str, context: AgentContext) -> list[SubTask]:
        """Decompose a high-level goal into structured SubTasks."""
        context.cancellation_token.throw_if_cancelled()

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Decompose this goal into subtasks:\n\n{goal}"},
        ]

        try:
            ai_text, _ = await self.ai.chat_completion_with_tools(messages, tools=None)
            subtasks = self._parse_decomposition(ai_text or "", goal)
            if subtasks:
                return subtasks[: self.max_subtasks]
        except Exception as exc:
            logger.warning("AI goal decomposition failed: %s — using heuristic planner", exc)

        # Fallback heuristic decomposition
        return self._heuristic_decomposition(goal)

    def _parse_decomposition(self, raw_text: str, original_goal: str) -> list[SubTask]:
        """Extract and validate JSON subtasks from AI response."""
        json_match = re.search(r"(\{.*\"subtasks\".*\})", raw_text, re.DOTALL)
        if not json_match:
            return []

        try:
            data = json.loads(json_match.group(1))
            items = data.get("subtasks", [])
            subtasks: list[SubTask] = []
            valid_agents = {"research", "memory", "browser", "task", "scheduler"}

            for idx, item in enumerate(items):
                st_id = item.get("id") or f"step_{idx + 1}"
                agent = (item.get("agent") or "research").strip().lower()
                if agent not in valid_agents:
                    agent = "research"
                desc = item.get("description") or f"Execute {agent} task"
                deps = item.get("dependencies") or []
                inp = item.get("input") or {}

                subtasks.append(SubTask(
                    subtask_id=st_id,
                    description=desc,
                    assigned_agent=agent,
                    dependencies=deps,
                    input_data=inp,
                ))
            return subtasks
        except Exception as exc:
            logger.warning("JSON parse error in plan decomposition: %s", exc)
            return []

    def _heuristic_decomposition(self, goal: str) -> list[SubTask]:
        """Rule-based fallback decomposition for common multi-agent queries."""
        lower = goal.lower()
        subtasks = []

        # If searching/jobs
        if any(w in lower for w in ("find", "search", "job", "research", "lookup")):
            subtasks.append(SubTask(
                subtask_id="step_1",
                description=f"Search information for: {goal}",
                assigned_agent="research",
                input_data={"action": "search", "query": goal},
            ))

        # If saving/remembering
        if any(w in lower for w in ("save", "remember", "store", "keep")):
            prev_dep = ["step_1"] if subtasks else []
            subtasks.append(SubTask(
                subtask_id="step_2" if subtasks else "step_1",
                description="Save relevant findings into persistent memory",
                assigned_agent="memory",
                dependencies=prev_dep,
                input_data={"action": "save", "content": "{{step_1.result}}", "category": "fact"},
            ))

        # If task creation
        if any(w in lower for w in ("task", "apply", "create task", "schedule", "remind", "todo")):
            prev_dep = [subtasks[-1].subtask_id] if subtasks else []
            subtasks.append(SubTask(
                subtask_id=f"step_{len(subtasks) + 1}",
                description="Create action task",
                assigned_agent="task",
                dependencies=prev_dep,
                input_data={"action": "add", "title": goal, "priority": "high"},
            ))

        if not subtasks:
            # Default single research subtask
            subtasks.append(SubTask(
                subtask_id="step_1",
                description=goal,
                assigned_agent="research",
                input_data={"query": goal},
            ))

        return subtasks

    async def plan_and_execute(
        self,
        goal: str,
        *,
        context: AgentContext | None = None,
    ) -> PlanResult:
        """Complete workflow: Decompose -> Delegate via Bus -> Synthesize."""
        start_time = time.perf_counter()
        plan_id = str(uuid.uuid4())[:8]
        ctx = context or AgentContext(context_id=plan_id)

        logger.info("PlannerAgent planning goal | plan_id=%s goal=%s", plan_id, goal[:80])

        # 1. Decompose goal
        subtasks = await self.decompose_goal(goal, ctx)
        completed_results: dict[str, Any] = {}

        # 2. Sequential execution of DAG subtasks
        for st in subtasks:
            ctx.cancellation_token.throw_if_cancelled()
            st.status = "in_progress"
            st_start = time.perf_counter()

            # Parameter resolution (interpolate {{step_id.result}})
            resolved_input = self._interpolate_inputs(st.input_data, completed_results)

            # Delegate subtask to target agent via EventBus
            delegate_msg = AgentMessage.create(
                sender=self.name,
                recipient=st.assigned_agent,
                msg_type=MessageType.SUBTASK_DELEGATION,
                payload={
                    "task": st.description,
                    "input": resolved_input,
                    "subtask_id": st.subtask_id,
                },
                context_id=ctx.context_id,
            )

            try:
                response = await self.event_bus.send_and_wait_response(
                    delegate_msg,
                    timeout=45.0,
                    retries=1,
                    cancellation_token=ctx.cancellation_token,
                )

                st.duration_sec = time.perf_counter() - st_start
                if response.type == MessageType.ERROR:
                    st.status = "failed"
                    st.error = response.payload.get("error", "Unknown error")
                else:
                    st.status = "completed"
                    st.result = response.payload.get("result")
                    completed_results[st.subtask_id] = st.result
                    # Record in context shared memory
                    ctx.set_shared(st.subtask_id, st.result)

            except asyncio.CancelledError:
                st.status = "cancelled"
                st.error = "Cancelled by user"
                break
            except Exception as exc:
                st.status = "failed"
                st.error = str(exc)
                logger.exception("Subtask %s failed: %s", st.subtask_id, exc)

        # 3. Synthesize final answer based on all subtasks
        synthesis = await self._synthesize_plan(goal, subtasks, ctx)
        total_dur = time.perf_counter() - start_time
        success = all(st.status == "completed" for st in subtasks)

        if self.activity:
            self.activity.log(
                "multi_agent",
                "plan_executed",
                f"plan_id={plan_id} subtasks={len(subtasks)} success={success} duration={total_dur:.2f}s",
            )

        return PlanResult(
            plan_id=plan_id,
            goal=goal,
            subtasks=subtasks,
            final_synthesis=synthesis,
            success=success,
            total_duration_sec=total_dur,
        )

    def _interpolate_inputs(
        self,
        raw_input: dict[str, Any],
        completed: dict[str, Any],
    ) -> dict[str, Any]:
        """Replace {{step_id.result}} tokens in input strings with actual output data."""
        resolved: dict[str, Any] = {}
        for k, v in raw_input.items():
            if isinstance(v, str):
                match = re.search(r"\{\{([a-zA-Z0-9_]+)\.result\}\}", v)
                if match:
                    dep_id = match.group(1)
                    dep_val = completed.get(dep_id, {})
                    # If dep_val is dict or output string
                    if isinstance(dep_val, dict) and "output" in dep_val:
                        dep_text = str(dep_val["output"])
                    else:
                        dep_text = str(dep_val)
                    v = v.replace(match.group(0), dep_text)
            resolved[k] = v
        return resolved

    async def _synthesize_plan(
        self,
        goal: str,
        subtasks: list[SubTask],
        context: AgentContext,
    ) -> str:
        """Synthesize all subtask results into a cohesive final answer."""
        results_summary = []
        for st in subtasks:
            status_icon = "✅" if st.status == "completed" else "❌"
            res_preview = str(st.result)[:300] if st.result else (st.error or "No output")
            results_summary.append(f"- [{st.subtask_id}] ({st.assigned_agent}) {status_icon}: {st.description}\n  Result: {res_preview}")

        synthesis_prompt = (
            f"You are Aru, Boss's personal AI assistant.\n"
            f"The Boss gave the goal:\n\"{goal}\"\n\n"
            f"The specialized agents executed the following subtasks:\n"
            + "\n".join(results_summary) +
            "\n\nSynthesize a complete, polished, and helpful answer for the Boss in the language they used (Bangla or English)."
        )

        try:
            messages = [{"role": "user", "content": synthesis_prompt}]
            reply, _ = await self.ai.chat_completion_with_tools(messages, tools=None)
            if reply and reply.strip():
                return reply.strip()
        except Exception as exc:
            logger.warning("Synthesis completion error: %s", exc)

        # Fallback formatted string
        return (
            f"বস, আপনার নির্দেশ (\"_{goal}_\") সম্পন্ন হয়েছে:\n\n"
            + "\n".join(f"• **{st.description}** ({st.status})" for st in subtasks)
        )
