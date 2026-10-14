"""Agent Event Bus for Sprint 6 Multi-Agent Autonomous Automation.

Provides asynchronous pub/sub, point-to-point messaging, execution tracing,
retries, timeout handling, and cooperative cancellation tokens.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.multi_agent.messages import AgentMessage

logger = logging.getLogger("aru.multi_agent.bus")


class CancellationToken:
    """Cooperative cancellation token for multi-agent workflows."""

    def __init__(self) -> None:
        self._is_cancelled = False
        self._reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._is_cancelled

    @property
    def reason(self) -> str | None:
        return self._reason

    def cancel(self, reason: str = "Operation cancelled by user or system") -> None:
        self._is_cancelled = True
        self._reason = reason

    def throw_if_cancelled(self) -> None:
        if self._is_cancelled:
            raise asyncio.CancelledError(self._reason or "Operation cancelled")


@dataclass
class EventTraceRecord:
    """Audit record for message dispatching on the event bus."""
    event_id: str
    topic: str
    sender: str
    recipient: str
    message_type: str
    timestamp: str
    duration_sec: float = 0.0
    status: str = "delivered"
    error: str | None = None


class AgentEventBus:
    """
    Central asynchronous event and message bus for Aru AI Multi-Agent System.
    Supports pub/sub broadcasting, point-to-point RPC, retries, and execution tracing.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[AgentMessage], Awaitable[Any]]]] = {}
        self._response_futures: dict[str, asyncio.Future[AgentMessage]] = {}
        self._trace_history: list[EventTraceRecord] = []
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        topic: str,
        handler: Callable[[AgentMessage], Awaitable[Any]],
    ) -> None:
        """Subscribe an async handler to a topic."""
        key = topic.strip().lower()
        if key not in self._subscribers:
            self._subscribers[key] = []
        if handler not in self._subscribers[key]:
            self._subscribers[key].append(handler)
            logger.debug("Subscribed handler to topic: %s", key)

    def unsubscribe(
        self,
        topic: str,
        handler: Callable[[AgentMessage], Awaitable[Any]],
    ) -> bool:
        """Unsubscribe a handler from a topic."""
        key = topic.strip().lower()
        if key in self._subscribers and handler in self._subscribers[key]:
            self._subscribers[key].remove(handler)
            return True
        return False

    async def publish(self, topic: str, message: "AgentMessage") -> int:
        """Broadcast a message to all subscribers of a topic."""
        key = topic.strip().lower()
        handlers = self._subscribers.get(key, [])
        delivered_count = 0
        start_time = time.perf_counter()

        for handler in handlers:
            try:
                # Dispatch handler
                asyncio.create_task(self._safe_invoke_handler(handler, message))
                delivered_count += 1
            except Exception as exc:
                logger.exception("Error dispatching handler for topic %s: %s", key, exc)

        dur = time.perf_counter() - start_time
        record = EventTraceRecord(
            event_id=str(uuid.uuid4())[:8],
            topic=key,
            sender=message.sender,
            recipient=message.recipient,
            message_type=message.type.value if hasattr(message.type, "value") else str(message.type),
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_sec=dur,
            status=f"broadcast_to_{delivered_count}",
        )
        self._trace_history.append(record)
        return delivered_count

    async def _safe_invoke_handler(
        self,
        handler: Callable[[AgentMessage], Awaitable[Any]],
        message: "AgentMessage",
    ) -> None:
        try:
            await handler(message)
        except Exception as exc:
            logger.error("Async handler error for message %s: %s", message.message_id, exc)

    async def send_message(self, message: "AgentMessage") -> None:
        """Directly deliver message to recipient topic or check response futures."""
        # 1. If this message is a reply to an ongoing RPC future, resolve it
        if message.reply_to_id and message.reply_to_id in self._response_futures:
            future = self._response_futures[message.reply_to_id]
            if not future.done():
                future.set_result(message)
                logger.debug("Resolved RPC response future for %s", message.reply_to_id)
                return

        # 2. Otherwise route to recipient's inbox topic
        recipient_topic = f"agent.{message.recipient.strip().lower()}"
        await self.publish(recipient_topic, message)

    async def send_and_wait_response(
        self,
        message: "AgentMessage",
        *,
        timeout: float = 30.0,
        retries: int = 1,
        cancellation_token: CancellationToken | None = None,
    ) -> "AgentMessage":
        """
        Point-to-point RPC: send message and await structured response from recipient.
        Supports timeouts, retries, and cancellation tokens.
        """
        from modules.multi_agent.messages import AgentMessage, MessageType

        last_error: Exception | None = None

        for attempt in range(1, retries + 2):
            if cancellation_token and cancellation_token.is_cancelled:
                raise asyncio.CancelledError(cancellation_token.reason or "Cancelled before send")

            start_time = time.perf_counter()
            loop = asyncio.get_running_loop()
            future: asyncio.Future[AgentMessage] = loop.create_future()
            self._response_futures[message.message_id] = future

            try:
                # Deliver to recipient inbox
                recipient_topic = f"agent.{message.recipient.strip().lower()}"
                await self.publish(recipient_topic, message)

                # Wait for reply
                reply = await asyncio.wait_for(future, timeout=timeout)
                dur = time.perf_counter() - start_time

                self._trace_history.append(EventTraceRecord(
                    event_id=str(uuid.uuid4())[:8],
                    topic=recipient_topic,
                    sender=message.sender,
                    recipient=message.recipient,
                    message_type="rpc_call_resolved",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    duration_sec=dur,
                    status="success",
                ))
                return reply

            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"Agent RPC to '{message.recipient}' timed out after {timeout}s (attempt {attempt}/{retries + 1})"
                )
                logger.warning("Agent RPC timeout: %s", last_error)
            except Exception as exc:
                last_error = exc
                logger.error("Agent RPC error to '%s': %s", message.recipient, exc)
            finally:
                self._response_futures.pop(message.message_id, None)

            if attempt <= retries:
                await asyncio.sleep(0.5 * attempt)

        # Build fallback error response if all retries failed
        error_msg = AgentMessage(
            message_id=str(uuid.uuid4())[:8],
            sender=message.recipient,
            recipient=message.sender,
            type=MessageType.ERROR,
            payload={"error": str(last_error), "failed": True},
            context_id=message.context_id,
            reply_to_id=message.message_id,
        )
        return error_msg

    def get_event_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent event trace history."""
        records = self._trace_history[-limit:]
        return [
            {
                "event_id": r.event_id,
                "topic": r.topic,
                "sender": r.sender,
                "recipient": r.recipient,
                "type": r.message_type,
                "duration_sec": round(r.duration_sec, 3),
                "status": r.status,
                "timestamp": r.timestamp,
            }
            for r in records
        ]

    def clear_history(self) -> None:
        self._trace_history.clear()
