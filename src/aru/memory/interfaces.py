"""Memory layer protocols and interfaces for ARU AI V4."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol
from aru.memory.models import ConversationMessage, MemoryFact


class IWorkingMemory(Protocol):
    """Protocol for short-term in-memory conversation buffer."""

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage: ...

    def get_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ConversationMessage]: ...

    def get_sliding_window(
        self,
        session_id: str,
        max_messages: int = 20,
        max_tokens: int | None = None,
    ) -> list[ConversationMessage]: ...

    def clear(self, session_id: str) -> None: ...


class IPersistentMemory(Protocol):
    """Protocol for long-term episodic persistent storage and FTS search."""

    async def store_fact(
        self,
        content: str,
        key: str | None = None,
        category: str = "general",
        tags: list[str] | None = None,
    ) -> int: ...

    async def get_fact(self, key: str) -> MemoryFact | None: ...

    async def search_facts(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[MemoryFact]: ...

    async def delete_fact(self, key: str) -> bool: ...

    async def list_facts(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[MemoryFact]: ...


SummarizationHook = Callable[[str, list[ConversationMessage]], Awaitable[str]]


class IMemoryService(Protocol):
    """Protocol for the unified Memory Service."""

    async def add_user_message(self, session_id: str, user_id: int, content: str) -> None: ...

    async def add_assistant_message(self, session_id: str, content: str) -> None: ...

    async def remember(
        self,
        content: str,
        key: str | None = None,
        category: str = "general",
        tags: list[str] | None = None,
    ) -> int: ...

    async def recall(self, query: str, limit: int = 5) -> list[MemoryFact]: ...

    async def get_prompt_context(
        self,
        session_id: str,
        query: str | None = None,
        max_history_messages: int = 20,
        max_history_tokens: int = 2000,
    ) -> dict[str, Any]: ...

    def register_summarization_hook(self, hook: SummarizationHook) -> None: ...
