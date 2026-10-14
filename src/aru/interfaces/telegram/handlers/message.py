"""Chat message handler for Telegram in ARU AI V4."""

from __future__ import annotations

from typing import Any
from aru.brain.models import LLMMessage
from aru.brain.prompts import PromptLoader
from aru.brain.router import LLMRouter
from aru.executor.engine import PlanExecutor
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext
from aru.memory.service import MemoryService
from aru.planner.decomposer import GoalDecomposer
from aru.planner.models import Goal
from aru.tools.models import ExecutionContext


class MessageHandler:
    """Processes conversational messages and drives cognitive planning and execution."""

    def __init__(
        self,
        memory_service: MemoryService | None = None,
        goal_decomposer: GoalDecomposer | None = None,
        plan_executor: PlanExecutor | None = None,
        router: LLMRouter | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self._memory = memory_service
        self._decomposer = goal_decomposer
        self._executor = plan_executor
        self._router = router
        self._prompt_loader = prompt_loader or PromptLoader()

    async def handle_message(self, ctx: TelegramUpdateContext) -> bool:
        """Handle incoming chat text."""
        text = ctx.text.strip()
        if not text or text.startswith("/"):
            return False

        session_id = str(ctx.chat_id)

        # 1. Record incoming user message in memory
        if self._memory:
            await self._memory.add_user_message(session_id=session_id, user_id=ctx.user_id, content=text)

        # 2. Check if goal decomposition and tool execution is appropriate
        lower = text.lower()
        needs_tool = any(kw in lower for kw in ("calculate", "compute", "search", "remember", "recall"))

        if needs_tool and self._decomposer and self._executor:
            goal = Goal(description=text, user_id=ctx.user_id, session_id=session_id)
            plan = await self._decomposer.decompose(goal)
            exec_ctx = ExecutionContext(user_id=ctx.user_id, is_boss=ctx.is_boss)
            history = await self._executor.execute_plan(plan, context=exec_ctx)

            if history.final_output is not None:
                reply = f"✅ **Result:**\n{history.final_output}"
            elif history.error:
                reply = f"❌ **Error executing plan:**\n{history.error}"
            else:
                reply = "Completed plan."

            ctx.reply_text = reply
            ctx.handled = True

            if self._memory:
                await self._memory.add_assistant_message(session_id=session_id, content=reply)
            return True

        # 3. Conversational inference via Brain router
        if self._router and self._router.get_available_providers():
            # Build context from memory
            context_data = await self._memory.get_prompt_context(session_id=session_id, query=text) if self._memory else {}
            relevant_facts = [f.content for f in context_data.get("relevant_facts", [])]

            sys_msg = self._prompt_loader.build_system_message(
                boss_name="Boss" if ctx.is_boss else "User",
                relevant_memories=relevant_facts,
            )

            messages = [sys_msg]
            for m in context_data.get("recent_messages", []):
                messages.append(LLMMessage(role=m.role, content=m.content))  # type: ignore[arg-type]

            # If recent_messages didn't have current turn, append it
            if not any(m.content == text for m in messages[1:]):
                messages.append(LLMMessage(role="user", content=text))

            resp = await self._router.generate(messages)
            reply = resp.content
            ctx.reply_text = reply
            ctx.handled = True

            if self._memory:
                await self._memory.add_assistant_message(session_id=session_id, content=reply)
            return True

        # Fallback default echo reply if no brain configured
        fallback_reply = f"Echo: {text}"
        ctx.reply_text = fallback_reply
        ctx.handled = True
        return True
