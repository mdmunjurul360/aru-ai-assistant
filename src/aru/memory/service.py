"""Unified Memory Service orchestrating working and persistent memory for ARU AI V4."""

from __future__ import annotations

from typing import Any
from aru.core.logging import StructuredLogger
from aru.database.repositories.conversation_repo import ConversationRepository
from aru.memory.interfaces import (
    IMemoryService,
    IPersistentMemory,
    IWorkingMemory,
    SummarizationHook,
)
from aru.memory.models import ConversationMessage, MemoryFact
from aru.memory.persistent_memory import PersistentMemory
from aru.memory.working_memory import WorkingMemory


class MemoryService(IMemoryService):
    """
    High-level memory orchestrator coordinating short-term conversational context,
    episodic long-term fact storage, and dynamic summarization hooks.
    """

    def __init__(
        self,
        working_memory: IWorkingMemory | None = None,
        persistent_memory: IPersistentMemory | None = None,
        conversation_repo: ConversationRepository | None = None,
        logger: StructuredLogger | None = None,
        summarization_threshold: int = 20,
    ) -> None:
        self._working = working_memory or WorkingMemory()
        self._persistent = persistent_memory
        self._conversation_repo = conversation_repo
        self._logger = logger or StructuredLogger("aru.memory.service")
        self._summarization_threshold = summarization_threshold
        self._summarization_hooks: list[SummarizationHook] = []
        self._session_summaries: dict[str, str] = {}

    @property
    def working_memory(self) -> IWorkingMemory:
        return self._working

    @property
    def persistent_memory(self) -> IPersistentMemory | None:
        return self._persistent

    def register_summarization_hook(self, hook: SummarizationHook) -> None:
        """Register a hook to be invoked when message threshold is reached."""
        self._summarization_hooks.append(hook)

    async def add_user_message(
        self,
        session_id: str,
        user_id: int,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        """Record a user message to both working buffer and persistent database."""
        msg = self._working.add_message(session_id, role="user", content=content, metadata=metadata)
        if self._conversation_repo:
            try:
                await self._conversation_repo.add_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="user",
                    content=content,
                    metadata=metadata,
                )
            except Exception as err:
                self._logger.warning("Failed to persist user message: %s", err)

        await self._check_summarization(session_id)
        return msg

    async def add_assistant_message(
        self,
        session_id: str,
        content: str,
        user_id: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        """Record assistant response to both working buffer and persistent database."""
        msg = self._working.add_message(session_id, role="assistant", content=content, metadata=metadata)
        if self._conversation_repo:
            try:
                await self._conversation_repo.add_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content=content,
                    metadata=metadata,
                )
            except Exception as err:
                self._logger.warning("Failed to persist assistant message: %s", err)

        await self._check_summarization(session_id)
        return msg

    async def _check_summarization(self, session_id: str) -> None:
        """Invoke registered summarization hooks if session message count exceeds threshold."""
        if not self._summarization_hooks:
            return

        msgs = self._working.get_messages(session_id)
        if len(msgs) >= self._summarization_threshold:
            for hook in self._summarization_hooks:
                try:
                    summary = await hook(session_id, msgs)
                    if summary:
                        self._session_summaries[session_id] = summary
                        self._logger.info("Summarization generated for session: %s", session_id)
                except Exception as err:
                    self._logger.error("Summarization hook error: %s", err)

    async def remember(
        self,
        content: str,
        key: str | None = None,
        category: str = "general",
        tags: list[str] | None = None,
    ) -> int:
        """Store long-term episodic knowledge or preference."""
        if self._persistent is None:
            raise RuntimeError("Persistent memory is not configured on MemoryService.")
        return await self._persistent.store_fact(
            content=content,
            key=key,
            category=category,
            tags=tags,
        )

    async def recall(self, query: str, limit: int = 5) -> list[MemoryFact]:
        """Recall relevant long-term facts using full-text search."""
        if self._persistent is None:
            return []
        return await self._persistent.search_facts(query=query, limit=limit)

    async def get_prompt_context(
        self,
        session_id: str,
        query: str | None = None,
        max_history_messages: int = 20,
        max_history_tokens: int = 2000,
    ) -> dict[str, Any]:
        """
        Synthesize prompt context: sliding conversation window,
        retrieved relevant persistent memories, and running summary.
        """
        # 1. Sliding conversation window
        recent_messages = self._working.get_sliding_window(
            session_id=session_id,
            max_messages=max_history_messages,
            max_tokens=max_history_tokens,
        )

        # 2. Retrieved long-term facts
        relevant_facts: list[MemoryFact] = []
        if query and self._persistent:
            relevant_facts = await self._persistent.search_facts(query=query, limit=5)

        # 3. Running session summary if available
        summary = self._session_summaries.get(session_id)

        return {
            "session_id": session_id,
            "recent_messages": recent_messages,
            "relevant_facts": relevant_facts,
            "summary": summary,
        }
