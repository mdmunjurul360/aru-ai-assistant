"""Structured message schemas, execution context, and plan definitions for Multi-Agent Aru."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from modules.multi_agent.event_bus import CancellationToken


class MessageType(str, Enum):
    """Categorization of inter-agent messages."""
    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    SUBTASK_DELEGATION = "subtask_delegation"
    STATUS_UPDATE = "status_update"
    NOTIFICATION = "notification"
    BROADCAST = "broadcast"
    ERROR = "error"
    CANCEL = "cancel"


@dataclass
class AgentMessage:
    """Standard message unit transferred across the AgentEventBus."""
    message_id: str
    sender: str
    recipient: str
    type: MessageType
    payload: dict[str, Any]
    context_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reply_to_id: str | None = None

    @classmethod
    def create(
        cls,
        sender: str,
        recipient: str,
        msg_type: MessageType,
        payload: dict[str, Any],
        context_id: str,
        reply_to_id: str | None = None,
    ) -> AgentMessage:
        return cls(
            message_id=str(uuid.uuid4())[:8],
            sender=sender.strip().lower(),
            recipient=recipient.strip().lower(),
            type=msg_type,
            payload=payload,
            context_id=context_id,
            reply_to_id=reply_to_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "type": self.type.value if hasattr(self.type, "value") else str(self.type),
            "payload": self.payload,
            "context_id": self.context_id,
            "timestamp": self.timestamp,
            "reply_to_id": self.reply_to_id,
        }


@dataclass
class AgentContext:
    """Shared execution context carrying state, user authority, and artifacts across agents."""
    context_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: int = 1
    is_boss: bool = True
    shared_memory: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_shared(self, key: str, value: Any) -> None:
        self.shared_memory[key] = value

    def get_shared(self, key: str, default: Any = None) -> Any:
        return self.shared_memory.get(key, default)


@dataclass
class SubTask:
    """A decomposed subtask allocated to a specialized agent."""
    subtask_id: str
    description: str
    assigned_agent: str
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, completed, failed, cancelled
    input_data: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    duration_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.subtask_id,
            "description": self.description,
            "agent": self.assigned_agent,
            "dependencies": self.dependencies,
            "status": self.status,
            "input": self.input_data,
            "result": self.result,
            "error": self.error,
            "duration_sec": round(self.duration_sec, 3),
        }


@dataclass
class PlanResult:
    """Outcome of a goal decomposed and executed by the multi-agent system."""
    plan_id: str
    goal: str
    subtasks: list[SubTask]
    final_synthesis: str
    success: bool
    total_duration_sec: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "success": self.success,
            "total_duration_sec": round(self.total_duration_sec, 3),
            "subtasks_count": len(self.subtasks),
            "subtasks": [st.to_dict() for st in self.subtasks],
            "final_synthesis": self.final_synthesis,
            "error": self.error,
        }

    def format_plan(self) -> str:
        """Markdown view of the executed plan and subtask outcomes."""
        lines = [
            f"📋 **Multi-Agent Execution Plan (`{self.plan_id}`)**",
            f"Goal: _{self.goal}_",
            f"Status: {'✅ Succeeded' if self.success else '❌ Failed'} | Duration: {self.total_duration_sec:.2f}s\n",
        ]
        for st in self.subtasks:
            icon = "✅" if st.status == "completed" else ("❌" if st.status == "failed" else "⏳")
            lines.append(f"• **[{st.subtask_id}]** `{st.assigned_agent}` {icon}: {st.description}")
            if st.result:
                res_str = str(st.result).strip()
                if len(res_str) > 120:
                    res_str = res_str[:120] + "..."
                lines.append(f"   ↳ _Result:_ {res_str}")
            if st.error:
                lines.append(f"   ↳ _Error:_ {st.error}")

        lines.append(f"\n💬 **সারাংশ:**\n{self.final_synthesis}")
        return "\n".join(lines)
