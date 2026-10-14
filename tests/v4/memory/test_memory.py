"""Unit tests for Phase 6: Memory Layer."""

from __future__ import annotations

from pathlib import Path
import pytest

from aru.database import (
    ConversationRepository,
    DatabaseManager,
    MemoryRepository,
    MigrationRunner,
)
from aru.memory import (
    ConversationMessage,
    MemoryFact,
    MemoryService,
    PersistentMemory,
    WorkingMemory,
)


@pytest.fixture
async def memory_db(tmp_path: Path) -> DatabaseManager:
    """Provide a fresh SQLite database with migrations applied."""
    db_file = tmp_path / "test_memory.db"
    db_manager = DatabaseManager(db_file)
    runner = MigrationRunner(db_manager)
    await runner.run()
    yield db_manager
    await db_manager.disconnect()


def test_conversation_message_token_estimation() -> None:
    """Verify estimated_tokens heuristic calculation."""
    msg = ConversationMessage(role="user", content="Hello world! How are you doing today?")
    assert msg.estimated_tokens > 5
    assert msg.estimated_tokens == (len(msg.content) // 4) + 4


def test_working_memory_sliding_window_and_pruning() -> None:
    """Verify WorkingMemory prunes by count and respects token budget."""
    wm = WorkingMemory(default_max_messages=10)
    session_id = "test_sess_1"

    # Add 12 messages (should keep only last 10)
    for i in range(12):
        wm.add_message(session_id, role="user" if i % 2 == 0 else "assistant", content=f"Message {i}")

    all_msgs = wm.get_messages(session_id)
    assert len(all_msgs) == 10
    assert all_msgs[0].content == "Message 2"
    assert all_msgs[-1].content == "Message 11"

    # Test count-based sliding window
    window_5 = wm.get_sliding_window(session_id, max_messages=5)
    assert len(window_5) == 5
    assert window_5[0].content == "Message 7"
    assert window_5[-1].content == "Message 11"

    # Test token-budget sliding window
    # Each "Message X" is around 2+4=6 tokens. If max_tokens is 20, should fit ~3 messages.
    budget_window = wm.get_sliding_window(session_id, max_messages=10, max_tokens=20)
    assert len(budget_window) <= 3
    assert budget_window[-1].content == "Message 11"


@pytest.mark.asyncio
async def test_persistent_memory_operations(memory_db: DatabaseManager) -> None:
    """Verify PersistentMemory stores facts, executes FTS search, and maps models."""
    mem_repo = MemoryRepository(memory_db)
    pm = PersistentMemory(mem_repo)

    fact_id = await pm.store_fact(
        key="boss_city",
        content="Boss lives in Dhaka, Bangladesh",
        category="location",
        tags=["home", "dhaka"],
    )
    assert fact_id > 0

    fact = await pm.get_fact("boss_city")
    assert fact is not None
    assert isinstance(fact, MemoryFact)
    assert fact.content == "Boss lives in Dhaka, Bangladesh"
    assert fact.category == "location"
    assert "dhaka" in fact.tags

    # FTS search
    results = await pm.search_facts("Dhaka")
    assert len(results) >= 1
    assert results[0].key == "boss_city"

    # Delete
    deleted = await pm.delete_fact("boss_city")
    assert deleted is True
    assert await pm.get_fact("boss_city") is None


@pytest.mark.asyncio
async def test_memory_service_orchestration(memory_db: DatabaseManager) -> None:
    """Verify MemoryService coordinates working memory, persistence, and summarization hook."""
    mem_repo = MemoryRepository(memory_db)
    conv_repo = ConversationRepository(memory_db)
    pm = PersistentMemory(mem_repo)
    wm = WorkingMemory()

    service = MemoryService(
        working_memory=wm,
        persistent_memory=pm,
        conversation_repo=conv_repo,
        summarization_threshold=4,
    )

    summarized_sessions: list[str] = []

    async def mock_summarizer(sess_id: str, msgs: list[ConversationMessage]) -> str:
        summarized_sessions.append(sess_id)
        return f"Summary of {len(msgs)} messages"

    service.register_summarization_hook(mock_summarizer)

    session_id = "user_chat_1"

    # Add messages up to threshold
    await service.add_user_message(session_id, user_id=1, content="What is the project status?")
    await service.add_assistant_message(session_id, content="Everything is on schedule.")
    await service.add_user_message(session_id, user_id=1, content="Can we deploy tomorrow?")
    assert len(summarized_sessions) == 0

    # 4th message reaches threshold
    await service.add_assistant_message(session_id, content="Yes, Phase 6 will be complete.")
    assert len(summarized_sessions) == 1
    assert summarized_sessions[0] == session_id

    # Remember a fact
    await service.remember("Project launch target is Q4", key="launch_target", category="project")

    # Get prompt context
    context = await service.get_prompt_context(session_id=session_id, query="launch")
    assert len(context["recent_messages"]) == 4
    assert len(context["relevant_facts"]) == 1
    assert context["relevant_facts"][0].key == "launch_target"
    assert context["summary"] == "Summary of 4 messages"
