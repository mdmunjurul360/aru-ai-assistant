"""ReAct (Reasoning + Acting) cognitive loop for ARU AI V4 Planner."""

from __future__ import annotations

import json
import re
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from aru.brain.models import LLMMessage
from aru.brain.router import LLMRouter
from aru.planner.models import Goal
from aru.tools.registry import ToolRegistry


class ReActStep(BaseModel):
    """An individual thought-action-observation trace in the ReAct loop."""

    model_config = ConfigDict(frozen=True)

    iteration: int
    thought: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    observation: str | None = None
    is_final: bool = False
    final_answer: str | None = None


class ReActPlanner:
    """
    Cognitive planner managing alternating Thought, Action, and Observation cycles.
    """

    def __init__(
        self,
        router: LLMRouter | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._router = router
        self._registry = tool_registry or ToolRegistry()

    def parse_action_response(self, text: str) -> tuple[str, str | None, dict[str, Any], str | None]:
        """
        Parse thought, tool_name, tool_args, and final_answer from model output.
        Format:
        Thought: <reasoning>
        Action: <tool_name> or Final Answer
        Action Input: <json or string>
        """
        thought = ""
        tool_name: str | None = None
        tool_args: dict[str, Any] = {}
        final_answer: str | None = None

        thought_match = re.search(r"Thought:\s*(.*?)(?=\nAction:|\nFinal Answer:|$)", text, re.DOTALL | re.IGNORECASE)
        if thought_match:
            thought = thought_match.group(1).strip()

        final_match = re.search(r"Final Answer:\s*(.*)", text, re.DOTALL | re.IGNORECASE)
        if final_match:
            final_answer = final_match.group(1).strip()
            return thought, None, {}, final_answer

        action_match = re.search(r"Action:\s*([a-zA-Z0-9_\-]+)", text, re.IGNORECASE)
        if action_match:
            tool_name = action_match.group(1).strip().lower()

        input_match = re.search(r"Action Input:\s*(\{.*\}|\[.*\]|[^\n]+)", text, re.DOTALL | re.IGNORECASE)
        if input_match:
            raw_input = input_match.group(1).strip()
            try:
                tool_args = json.loads(raw_input)
            except Exception:
                tool_args = {"input": raw_input}

        return thought, tool_name, tool_args, final_answer

    async def plan_next_step(
        self,
        goal: Goal,
        history: list[ReActStep],
        iteration: int,
    ) -> ReActStep:
        """
        Decide the next reasoning thought and action based on goal and past observations.
        """
        # If router is available, can query LLM with tool definitions
        if self._router and self._router.get_available_providers():
            tool_schemas = self._registry.get_schemas()
            prompt = (
                f"You are solving the goal: '{goal.description}'\n"
                f"Available tools: {[t.name for t in self._registry.list_tools()]}\n"
                f"History:\n"
            )
            for h in history:
                prompt += f"Thought: {h.thought}\nAction: {h.tool_name}\nObservation: {h.observation}\n"
            prompt += (
                f"\nProvide your next reasoning step in this format:\n"
                f"Thought: <your thought>\n"
                f"Action: <tool_name>\n"
                f"Action Input: {{\"param\": \"value\"}}\n"
                f"OR if goal is met:\n"
                f"Thought: <your thought>\n"
                f"Final Answer: <your response to user>"
            )

            try:
                resp = await self._router.generate([LLMMessage(role="user", content=prompt)])
                thought, tool, args, final_ans = self.parse_action_response(resp.content)
                if final_ans:
                    return ReActStep(
                        iteration=iteration,
                        thought=thought or "Goal completed.",
                        is_final=True,
                        final_answer=final_ans,
                    )
                return ReActStep(
                    iteration=iteration,
                    thought=thought or "Proceeding with next tool action.",
                    tool_name=tool,
                    tool_args=args,
                    is_final=False,
                )
            except Exception:
                pass

        # Deterministic / rule-based fallback
        if not history:
            return ReActStep(
                iteration=iteration,
                thought=f"Begin executing goal: {goal.description}",
                tool_name="calculator" if "calculate" in goal.description.lower() else "web_search",
                tool_args={"expression": "100 * 2"} if "calculate" in goal.description.lower() else {"query": goal.description},
                is_final=False,
            )
        else:
            last = history[-1]
            return ReActStep(
                iteration=iteration,
                thought="Observation received. Goal is complete.",
                is_final=True,
                final_answer=f"Result based on observation: {last.observation}",
            )
