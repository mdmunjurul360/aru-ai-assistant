"""MemoryService abstraction layer unifying persistent conversation and long-term memory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from modules.config import CONVERSATION_HISTORY_LIMIT, DATABASE_PATH
from modules.conversation import ConversationHistoryStore, ConversationMessage
from modules.memory import MemoryItem, MemoryStore
from modules.semantic_memory.compression import ContextCompressor
from modules.semantic_memory.hybrid_search import HybridSearchEngine, HybridSearchResult
from modules.semantic_memory.vector_store import VectorMemoryStore

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger

logger = logging.getLogger("aru.memory_service")


class MemoryService:
    """
    Unified memory service abstraction layer.
    
    Decouples application logic from underlying storage engines.
    Provides standard interfaces for:
      - Multi-turn conversation context
      - Structured long-term memories (facts, preferences, goals, projects)
      - FTS5 keyword retrieval & Vector semantic embedding retrieval via RRF Hybrid Search
      - Context compression for efficient LLM prompting
    """

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        conversation_store: ConversationHistoryStore | None = None,
        db_path: str | Path | None = None,
        activity: "ActivityLogger | None" = None,
        vector_store: VectorMemoryStore | None = None,
    ) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self._activity = activity
        self.memory_store = memory_store or MemoryStore(db_path=self.db_path, activity=activity)
        self.conversation_store = conversation_store or ConversationHistoryStore(db_path=self.db_path)
        self.vector_store = vector_store or VectorMemoryStore(db_path=self.db_path)
        self.hybrid_engine = HybridSearchEngine(
            memory_store=self.memory_store,
            vector_store=self.vector_store,
        )
        self.compressor = ContextCompressor()

    # -------------------------------------------------------------------------
    # Conversation History Management
    # -------------------------------------------------------------------------

    def get_conversation_context(
        self,
        chat_id: int,
        limit: int = CONVERSATION_HISTORY_LIMIT,
        compress: bool = True,
    ) -> list[dict[str, str]]:
        """
        Retrieve recent conversation history for chat_id formatted for LLM completion.
        Applies smart context compression to prevent token explosion and slow queries.
        """
        raw = self.conversation_store.get_history(chat_id, limit=limit)
        if compress and self.compressor:
            return self.compressor.compress_conversation_history(raw, max_turns=min(limit, 10))
        return raw

    def record_user_message(self, chat_id: int, message: str) -> ConversationMessage:
        """Persist a user message into conversation history."""
        return self.conversation_store.add_message(chat_id, "user", message)

    def record_assistant_message(self, chat_id: int, message: str) -> ConversationMessage:
        """Persist an assistant message into conversation history."""
        return self.conversation_store.add_message(chat_id, "assistant", message)

    def record_interaction(
        self,
        chat_id: int,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        """Persist both sides of an interaction turn atomically with automatic pruning."""
        if user_message:
            self.conversation_store.add_message(chat_id, "user", user_message)
        if assistant_reply:
            self.conversation_store.add_message(chat_id, "assistant", assistant_reply)
        try:
            self.conversation_store.prune_history(chat_id, keep_last=60)
        except Exception as exc:
            logger.debug("Auto-pruning notice: %s", exc)

    def clear_conversation(self, chat_id: int) -> int:
        """Clear all conversation history for a given chat."""
        count = self.conversation_store.clear_history(chat_id)
        if self._activity:
            self._activity.log("memory", "CONVERSATION_CLEARED", f"chat_id={chat_id} count={count}")
        return count

    # -------------------------------------------------------------------------
    # Context Synthesis for AI Prompting
    # -------------------------------------------------------------------------

    def build_context_for_prompt(self, user_message: str, max_memories: int = 8) -> str:
        """
        Synthesize relevant long-term memory context for a given prompt/query.
        Preserves backward-compatible format expected by AruAI.
        """
        return self.memory_store.context_for_ai(user_message, limit=max_memories)

    # -------------------------------------------------------------------------
    # Long-term Memory Operations (FTS5 & Logical Memory Types)
    # -------------------------------------------------------------------------

    def save_memory(
        self,
        title: str,
        content: str,
        category: str = "fact",
        tags: str = "",
    ) -> MemoryItem:
        """Save a new memory item and index into dense vector store."""
        item = self.memory_store.save(title, content, category=category, tags=tags)
        try:
            self.hybrid_engine.index_memory_item(item)
        except Exception as exc:
            logger.warning("Vector indexing notice: %s", exc)
        return item

    def save_fact(self, title: str, content: str, tags: str = "") -> MemoryItem:
        """Save a factual knowledge memory."""
        return self.save_memory(title, content, category="fact", tags=tags)

    def save_preference(self, title: str, content: str, tags: str = "") -> MemoryItem:
        """Save a user preference memory."""
        return self.save_memory(title, content, category="preference", tags=tags)

    def save_goal(self, title: str, content: str, tags: str = "") -> MemoryItem:
        """Save an active user goal memory."""
        return self.save_memory(title, content, category="goal", tags=tags)

    def save_project(self, title: str, content: str, tags: str = "") -> MemoryItem:
        """Save an ongoing project memory."""
        return self.save_memory(title, content, category="project", tags=tags)

    def get_facts(self, limit: int = 50) -> list[MemoryItem]:
        """List stored facts."""
        return self.memory_store.get_facts(limit=limit)

    def get_preferences(self, limit: int = 50) -> list[MemoryItem]:
        """List stored preferences."""
        return self.memory_store.get_preferences(limit=limit)

    def get_goals(self, limit: int = 50) -> list[MemoryItem]:
        """List stored goals."""
        return self.memory_store.get_goals(limit=limit)

    def get_projects(self, limit: int = 50) -> list[MemoryItem]:
        """List stored projects."""
        return self.memory_store.get_projects(limit=limit)

    def search(
        self,
        query: str,
        limit: int = 5,
        category: str | None = None,
    ) -> list[MemoryItem]:
        """Full-text search across memories using FTS5 rank ordering."""
        return self.memory_store.search(query, limit=limit, category=category)

    def search_semantic(
        self,
        query: str,
        limit: int = 5,
        category: str | None = None,
    ) -> list[MemoryItem]:
        """
        Semantic search combining FTS5 BM25 keyword matching with
        Dense Vector similarity via Reciprocal Rank Fusion (RRF).
        """
        hybrid_res = self.search_hybrid(query, limit=limit, category=category)
        items: list[MemoryItem] = []
        for r in hybrid_res:
            if r.memory_id:
                m = self.memory_store.get(r.memory_id)
                if m:
                    items.append(m)
        if not items:
            return self.memory_store.search(query, limit=limit, category=category)
        return items

    def search_hybrid(
        self,
        query: str,
        limit: int = 5,
        category: str | None = None,
    ) -> list[HybridSearchResult]:
        """Execute hybrid search returning RRF ranked results."""
        return self.hybrid_engine.search(query, limit=limit, category=category)

    def get(self, memory_id: int) -> MemoryItem | None:
        """Retrieve memory by ID."""
        return self.memory_store.get(memory_id)

    def update(
        self,
        memory_id: int,
        title: str | None = None,
        content: str | None = None,
        category: str | None = None,
        tags: str | None = None,
    ) -> MemoryItem | None:
        """Update an existing memory and refresh vector index."""
        updated = self.memory_store.update(
            memory_id,
            title=title,
            content=content,
            category=category,
            tags=tags,
        )
        if updated:
            try:
                self.hybrid_engine.index_memory_item(updated)
            except Exception as exc:
                logger.warning("Vector re-index notice: %s", exc)
        return updated

    def delete(self, memory_id: int) -> bool:
        """Delete memory by ID and purge vector index."""
        ok = self.memory_store.delete(memory_id)
        if ok:
            try:
                self.vector_store.delete_by_memory_id(memory_id)
            except Exception as exc:
                logger.warning("Vector delete notice: %s", exc)
        return ok

    def list_all(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        """List all memories optionally filtered by category."""
        return self.memory_store.list_all(category=category, limit=limit)
