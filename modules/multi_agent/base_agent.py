"""Abstract base class for all specialized agents in Aru Multi-Agent system."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from modules.multi_agent.messages import AgentMessage, MessageType, AgentContext

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.multi_agent.event_bus import AgentEventBus

logger = logging.getLogger("aru.multi_agent.base")


class BaseSpecializedAgent(ABC):
    """
    Base contract for specialized agents (ResearchAgent, MemoryAgent, BrowserAgent, etc.).
    Communicates via AgentEventBus and processes structured subtasks.
    """

    name: str
    role: str
    description: str

    def __init__(
        self,
        event_bus: AgentEventBus,
        activity: ActivityLogger | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.activity = activity
        self._running = False
        self._inbox_topic = f"agent.{self.name.strip().lower()}"

    def start(self) -> None:
        """Register agent inbox with the event bus."""
        if not self._running:
            self.event_bus.subscribe(self._inbox_topic, self._on_inbox_message)
            self._running = True
            logger.info("Specialized agent '%s' online (topic: %s)", self.name, self._inbox_topic)

    def stop(self) -> None:
        """Deregister agent inbox."""
        if self._running:
            self.event_bus.unsubscribe(self._inbox_topic, self._on_inbox_message)
            self._running = False
            logger.info("Specialized agent '%s' offline", self.name)

    async def _on_inbox_message(self, message: AgentMessage) -> None:
        """Internal router for incoming bus messages."""
        if message.type in (MessageType.TASK_REQUEST, MessageType.SUBTASK_DELEGATION):
            try:
                # Reconstruct or provide a default context
                ctx = AgentContext(context_id=message.context_id)
                task_desc = message.payload.get("task", "")
                input_data = message.payload.get("input", {})

                result = await self.execute_task(task_desc, input_data, ctx)
                # Reply back
                response_msg = AgentMessage.create(
                    sender=self.name,
                    recipient=message.sender,
                    msg_type=MessageType.TASK_RESPONSE,
                    payload={"result": result, "success": True},
                    context_id=message.context_id,
                    reply_to_id=message.message_id,
                )
                await self.event_bus.send_message(response_msg)
            except Exception as exc:
                logger.exception("Agent %s failed to process message %s: %s", self.name, message.message_id, exc)
                error_msg = AgentMessage.create(
                    sender=self.name,
                    recipient=message.sender,
                    msg_type=MessageType.ERROR,
                    payload={"error": str(exc), "success": False},
                    context_id=message.context_id,
                    reply_to_id=message.message_id,
                )
                await self.event_bus.send_message(error_msg)

    @abstractmethod
    async def execute_task(
        self,
        task_description: str,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        """
        Execute domain-specific subtask.
        Returns a dictionary payload representing output and artifacts.
        """
        raise NotImplementedError
