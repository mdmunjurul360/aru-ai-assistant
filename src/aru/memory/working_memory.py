"""Working Memory implementation with sliding token window for ARU AI V4."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any
from aru.memory.interfaces import IWorkingMemory
from aru.memory.models import ConversationMessage


class WorkingMemory(IWorkingMemory):
    """
    Fast, thread-safe in-memory cache of recent conversational turns
    with sliding context window and token budgeting.
    """

    def __init__(self, default_max_messages: int = 50) -> None:
        self._sessions: dict[str, list[ConversationMessage]] = {}
        self._max_messages = default_max_messages
        self._lock = threading.Lock()

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        """Append a message to session buffer and prune to max messages."""
        now_str = datetime.now(timezone.utc).isoformat()
        msg = ConversationMessage(
            role=role,
            content=content,
            timestamp=now_str,
            metadata=metadata or {},
        )
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []
            buf = self._sessions[session_id]
            buf.append(msg)
            # Prune if over maximum limit
            if len(buf) > self._max_messages:
                self._sessions[session_id] = buf[-self._max_messages :]
        return msg

    def get_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ConversationMessage]:
        """Retrieve copies of conversation messages."""
        with self._lock:
            buf = list(self._sessions.get(session_id, []))
        if limit is not None and limit > 0:
            return buf[-limit:]
        return buf

    def get_sliding_window(
        self,
        session_id: str,
        max_messages: int = 20,
        max_tokens: int | None = 2000,
    ) -> list[ConversationMessage]:
        """
        Extract the most recent messages that fit both message count
        and token budget limits.
        """
        all_msgs = self.get_messages(session_id)
        if not all_msgs:
            return []

        # 1. Take up to max_messages from the tail
        candidates = all_msgs[-max_messages:]

        if max_tokens is None:
            return candidates

        # 2. Iterate backwards from newest message to fit within token budget
        fitted: list[ConversationMessage] = []
        accumulated_tokens = 0

        for msg in reversed(candidates):
            cost = msg.estimated_tokens
            if accumulated_tokens + cost > max_tokens and fitted:
                break
            fitted.append(msg)
            accumulated_tokens += cost

        # Return in original chronological order
        return list(reversed(fitted))

    def clear(self, session_id: str) -> None:
        """Clear in-memory buffer for a session."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def session_count(self) -> int:
        """Return total active in-memory sessions."""
        with self._lock:
            return len(self._sessions)
