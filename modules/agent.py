"""Autonomous Agent (ReAct + Tool Calling) for Aru AI.

Implements the Planner -> Tool -> Observe -> Reason -> Final Answer loop.
Directly interfaces with the MCP Tool Registry and executes multi-step workflows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from modules.config import (
    AGENT_MAX_ITERATIONS,
    AGENT_TIMEOUT_SECONDS,
    SYSTEM_PROMPT,
)
from modules.tools.base import ExecutionContext

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.ai import AruAI
    from modules.tools.manager import ToolManager

logger = logging.getLogger("aru.agent")

AGENT_INSTRUCTIONS = """You are Aru, the autonomous personal AI assistant of your Boss.
You have access to a real-world tool execution environment (MCP Tool Registry).
You can inspect and execute tools at any time during your reasoning cycle.

Available Capabilities:
• research: Grounded multi-provider web search, URL scraping, and persistent knowledge cache.
• browser: Live headless Chromium browser (Playwright) to navigate dynamic pages, extract DOM selectors, and take screenshots.
• file_reader: Sandboxed workspace reader to inspect code, documents, and directory structures.
• memory: SQLite FTS5 persistent memory to search facts (BM25), save new knowledge, list items, or delete memories.
• tasks: Smart task manager to create tasks with priority, list pending items, update statuses, and delete tasks.

ReAct Operating Instructions:
1. Think before acting: Analyze what the Boss needs. Break complex goals into sequential steps.
2. Multi-step Execution: If a task requires multiple tools (e.g., search web -> save memory -> create task), invoke them one after another.
3. Observe and Reason: After each tool execution, carefully read the observation and decide your next action.
4. Error Recovery: If a tool returns an error or empty result, do not give up. Reason about the cause, adjust your parameters, or use an alternative tool.
5. Final Answer: When all necessary tool steps are complete, synthesize a clear, helpful, and polite response in the language used by the Boss (Bangla or English).
6. If no tool is needed for a simple question or pleasantry, answer directly without calling any tools.
"""


@dataclass
class AgentStep:
    """A single step within the ReAct reasoning trace."""
    step_number: int
    tool: str
    tool_input: dict[str, Any]
    observation: str
    thought: str | None = None
    duration_sec: float = 0.0
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step_number,
            "thought": self.thought,
            "tool": self.tool,
            "input": self.tool_input,
            "observation": self.observation[:500] if len(self.observation) > 500 else self.observation,
            "duration_sec": round(self.duration_sec, 3),
            "success": self.success,
        }


@dataclass
class AgentTrace:
    """Complete execution trace of an autonomous agent run."""
    trace_id: str
    user_query: str
    steps: list[AgentStep] = field(default_factory=list)
    final_answer: str = ""
    total_duration_sec: float = 0.0
    iteration_count: int = 0
    loop_detected: bool = False
    error: str | None = None

    @property
    def total_tool_calls(self) -> int:
        return len(self.steps)

    @property
    def tools_used(self) -> list[str]:
        seen = []
        for s in self.steps:
            if s.tool not in seen:
                seen.append(s.tool)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "query": self.user_query,
            "iterations": self.iteration_count,
            "tool_calls_count": self.total_tool_calls,
            "tools_used": self.tools_used,
            "loop_detected": self.loop_detected,
            "total_duration_sec": round(self.total_duration_sec, 3),
            "steps": [s.to_dict() for s in self.steps],
            "final_answer": self.final_answer,
            "error": self.error,
        }

    def format_trace(self) -> str:
        """User-friendly markdown visualization of the execution trace."""
        lines = [
            f"🧭 **Agent Execution Trace (`{self.trace_id[:8]}`)**",
            f"Query: _{self.user_query}_",
            f"Total Tool Calls: {self.total_tool_calls} | Duration: {self.total_duration_sec:.2f}s\n",
        ]
        if not self.steps:
            lines.append("• কোনো টুল কল হয়নি (সরাসরি উত্তর প্রদান করা হয়েছে)।")
        for s in self.steps:
            status_icon = "✅" if s.success else "❌"
            lines.append(f"**Step {s.step_number}:** `{s.tool}` {status_icon} ({s.duration_sec:.2f}s)")
            if s.thought:
                lines.append(f"  _Thought:_ {s.thought}")
            lines.append(f"  _Input:_ `{json.dumps(s.tool_input, ensure_ascii=False)}`")
            preview = s.observation.strip()
            if len(preview) > 200:
                preview = preview[:200] + "..."
            lines.append(f"  _Observation:_ {preview}\n")

        if self.loop_detected:
            lines.append("⚠️ _লুপ সনাক্ত হওয়ায় টুল কল বন্ধ করা হয়েছে।_")
        return "\n".join(lines)


@dataclass
class AgentResponse:
    """Final output object returned by AruAgent."""
    reply: str
    trace: AgentTrace
    tool_calls_count: int


class AruAgent:
    """
    Autonomous ReAct Agent orchestrator for Aru AI.
    Combines Model Context Protocol tool discovery, iterative planning,
    resilient tool execution, loop detection, and structured trace auditing.
    """

    def __init__(
        self,
        ai: AruAI,
        tool_manager: ToolManager,
        activity: ActivityLogger | None = None,
        max_iterations: int = AGENT_MAX_ITERATIONS,
        timeout_seconds: float = AGENT_TIMEOUT_SECONDS,
    ) -> None:
        self.ai = ai
        self.tool_manager = tool_manager
        self.activity = activity
        self.max_iterations = max(1, max_iterations)
        self.timeout_seconds = timeout_seconds

    def get_tool_specs(self) -> list[dict[str, Any]]:
        """Export all registered MCP tools into OpenAI/Groq function calling schema."""
        specs: list[dict[str, Any]] = []
        for tool_schema in self.tool_manager.list_tools():
            name = tool_schema.get("name", "")
            desc = tool_schema.get("description", "")
            params = tool_schema.get("input_schema", {"type": "object", "properties": {}})
            specs.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": params,
                },
            })
        return specs

    def _detect_loop(
        self,
        tool_name: str,
        args: dict[str, Any],
        recent_calls: list[tuple[str, str]],
    ) -> bool:
        """Check if identical tool call with same arguments was repeated sequentially."""
        arg_key = json.dumps(args, sort_keys=True, ensure_ascii=False)
        current = (tool_name.lower(), arg_key)
        # If identical call happened twice consecutively, trigger loop defense
        if len(recent_calls) >= 2 and recent_calls[-1] == current and recent_calls[-2] == current:
            return True
        return False

    def _parse_text_react_fallback(self, text: str) -> list[dict[str, Any]]:
        """
        Fallback parser if an LLM outputs text-formatted ReAct actions
        instead of native JSON tool_calls.
        Matches patterns like: Action: <tool>\nAction Input: {...} or ```json {"tool": ...}
        """
        actions = []
        if not text:
            return actions

        # Pattern 1: Action: <tool>\nAction Input: <json>
        pattern_action = re.search(r"Action:\s*([a-zA-Z0-9_\-]+)\s*\nAction Input:\s*(\{.*?\})", text, re.DOTALL)
        if pattern_action:
            tool_name = pattern_action.group(1).strip()
            raw_input = pattern_action.group(2).strip()
            try:
                parsed_args = json.loads(raw_input)
                actions.append({"name": tool_name, "args": parsed_args})
                return actions
            except Exception:
                pass

        # Pattern 2: ```json {"tool": "...", "parameters": {...}} ```
        pattern_json = re.search(r"```(?:json)?\s*(\{\s*\"tool\".*?\})\s*```", text, re.DOTALL)
        if pattern_json:
            try:
                data = json.loads(pattern_json.group(1))
                if "tool" in data:
                    t_name = data["tool"]
                    t_args = data.get("arguments") or data.get("parameters") or {}
                    actions.append({"name": t_name, "args": t_args})
                    return actions
            except Exception:
                pass

        return actions

    async def run(
        self,
        user_message: str,
        *,
        context: ExecutionContext,
        memory_context: str = "",
        conversation_history: list[dict[str, str]] | None = None,
    ) -> AgentResponse:
        """
        Execute the autonomous ReAct cycle:
        Planner -> Tool Execution -> Observation -> Reflection -> Final Answer.
        """
        start_time = time.perf_counter()
        trace_id = str(uuid.uuid4())
        trace = AgentTrace(trace_id=trace_id, user_query=user_message)
        recent_call_history: list[tuple[str, str]] = []

        logger.info(
            "Autonomous Agent run started | trace_id=%s user_id=%s max_iter=%s query=%s",
            trace_id[:8],
            context.user_id,
            self.max_iterations,
            user_message[:80],
        )

        # 1. Prepare system instructions and conversation context
        full_system = f"{SYSTEM_PROMPT}\n\n{AGENT_INSTRUCTIONS}"
        if memory_context:
            full_system += f"\n\nPersistent memories about Boss:\n{memory_context}"

        messages: list[dict[str, Any]] = [{"role": "system", "content": full_system}]
        if conversation_history:
            messages.extend(conversation_history[-10:])
        messages.append({"role": "user", "content": user_message})

        tool_specs = self.get_tool_specs()

        # 2. Autonomous Loop
        iteration = 0
        final_answer: str | None = None

        while iteration < self.max_iterations:
            iteration += 1
            trace.iteration_count = iteration

            # Timeout check
            elapsed = time.perf_counter() - start_time
            if elapsed > self.timeout_seconds:
                logger.warning("Agent run exceeded timeout limit (%.2fs)", elapsed)
                trace.error = f"Agent execution exceeded overall timeout of {self.timeout_seconds}s"
                break

            logger.debug("Agent iteration %d/%d (elapsed: %.2fs)", iteration, self.max_iterations, elapsed)

            # Call AI with tool definitions
            ai_content, tool_calls = await self.ai.chat_completion_with_tools(
                messages,
                tools=tool_specs,
                tool_choice="auto",
            )

            # Check if native tool calls were returned
            if tool_calls:
                # Clean assistant message to append into conversation history
                clean_assistant: dict[str, Any] = {
                    "role": "assistant",
                    "content": ai_content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                messages.append(clean_assistant)

                for tc in tool_calls:
                    step_start = time.perf_counter()
                    t_name = tc.function.name.strip()
                    raw_args = tc.function.arguments

                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except Exception as exc:
                        logger.warning("Agent JSON decode error on tool %s: %s", t_name, exc)
                        args = {"raw": raw_args}

                    # Loop detection
                    if self._detect_loop(t_name, args, recent_call_history):
                        trace.loop_detected = True
                        observation = (
                            f"Warning: Tool '{t_name}' has already been called repeatedly with identical parameters. "
                            f"Loop prevention triggered. Do not repeat this call; synthesize your final answer."
                        )
                        success = False
                    else:
                        recent_call_history.append((t_name.lower(), json.dumps(args, sort_keys=True, ensure_ascii=False)))
                        # Execute tool safely via ToolManager
                        res = await self.tool_manager.execute_tool(t_name, args, context)
                        success = res.success
                        observation = res.format_output() if res.success else f"Tool Error: {res.error}"

                    step_dur = time.perf_counter() - step_start
                    step = AgentStep(
                        step_number=len(trace.steps) + 1,
                        thought=ai_content,
                        tool=t_name,
                        tool_input=args,
                        observation=observation,
                        duration_sec=step_dur,
                        success=success,
                    )
                    trace.steps.append(step)

                    # Append observation back to conversation messages (bounded to avoid token overflow)
                    obs_in_prompt = observation if len(observation) <= 800 else observation[:650] + "\n... [Observation trimmed for token budget] ...\n" + observation[-150:]
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": t_name,
                        "content": obs_in_prompt,
                    })

                # If loop was detected, break early to prevent runaway loop
                if trace.loop_detected:
                    break

                # Continue next iteration to observe tool results
                continue

            # If no native tool_calls, check for text-based ReAct fallback
            text_actions = self._parse_text_react_fallback(ai_content or "")
            if text_actions:
                for action_item in text_actions:
                    t_name = action_item["name"]
                    t_args = action_item["args"]
                    step_start = time.perf_counter()

                    res = await self.tool_manager.execute_tool(t_name, t_args, context)
                    step_dur = time.perf_counter() - step_start
                    observation = res.format_output() if res.success else f"Tool Error: {res.error}"

                    step = AgentStep(
                        step_number=len(trace.steps) + 1,
                        thought=ai_content,
                        tool=t_name,
                        tool_input=t_args,
                        observation=observation,
                        duration_sec=step_dur,
                        success=res.success,
                    )
                    trace.steps.append(step)

                    obs_in_prompt = observation if len(observation) <= 800 else observation[:650] + "\n... [Observation trimmed for token budget] ...\n" + observation[-150:]
                    messages.append({"role": "assistant", "content": ai_content or ""})
                    messages.append({
                        "role": "user",
                        "content": f"Observation from {t_name}:\n{obs_in_prompt}\n\nContinue or provide final answer.",
                    })
                continue

            # No tool calls and no fallback actions -> This is the Final Answer!
            final_answer = ai_content or ""
            break

        # 3. If loop terminated without a direct final answer, perform final synthesis
        if final_answer is None or not final_answer.strip():
            logger.info("Agent synthesizing final answer after %d tool steps", len(trace.steps))
            synthesis_prompt = (
                "You have gathered all the observations above. "
                "Synthesize your final answer to the Boss clearly and comprehensively. "
                "Do not invoke any more tools."
            )
            messages.append({"role": "user", "content": synthesis_prompt})
            final_content, _ = await self.ai.chat_completion_with_tools(messages, tools=None)
            final_answer = final_content or "দুঃখিত বস, কাজ সম্পন্ন হয়েছে কিন্তু চূড়ান্ত উত্তর গঠন করা যায়নি।"

        total_duration = time.perf_counter() - start_time
        trace.total_duration_sec = total_duration
        trace.final_answer = final_answer

        logger.info(
            "Autonomous Agent completed | trace_id=%s tool_calls=%d duration=%.2fs",
            trace_id[:8],
            len(trace.steps),
            total_duration,
        )

        # Structured activity logging
        if self.activity:
            self.activity.log(
                "autonomous_agent",
                "react_run",
                f"trace={trace_id[:8]} tools={','.join(trace.tools_used) or 'none'} steps={len(trace.steps)} duration={total_duration:.2f}s",
            )

        return AgentResponse(
            reply=final_answer,
            trace=trace,
            tool_calls_count=len(trace.steps),
        )
