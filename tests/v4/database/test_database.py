"""Unit tests for Phase 5: Database Layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from aru.core.di import Container
from aru.database import (
    AntiSpamRepository,
    ConversationRepository,
    DatabaseManager,
    MemoryRepository,
    MigrationRunner,
    TaskRepository,
)


@pytest.fixture
async def test_db(tmp_path: Path) -> DatabaseManager:
    """Provide a fresh SQLite database with migrations applied."""
    db_file = tmp_path / "test_aru_v4.db"
    db_manager = DatabaseManager(db_file)
    runner = MigrationRunner(db_manager)
    await runner.run()
    yield db_manager
    await db_manager.disconnect()


@pytest.mark.asyncio
async def test_database_manager_lifecycle(tmp_path: Path) -> None:
    """Verify connection lifecycle, WAL mode, and health check."""
    db_file = tmp_path / "lifecycle.db"
    db = DatabaseManager(db_file)

    assert not db.is_connected
    await db.connect()
    assert db.is_connected

    health = await db.check_health()
    assert health["status"] == "healthy"
    assert health["journal_mode"] == "WAL"

    await db.disconnect()
    assert not db.is_connected


@pytest.mark.asyncio
async def test_migration_runner_idempotency(tmp_path: Path) -> None:
    """Verify migration runner applies scripts once and is idempotent."""
    db_file = tmp_path / "migrations.db"
    db = DatabaseManager(db_file)
    runner = MigrationRunner(db)

    first_run = await runner.run()
    assert len(first_run) >= 1
    assert "001_initial_schema.sql" in first_run

    second_run = await runner.run()
    assert len(second_run) == 0  # No new migrations applied
    await db.disconnect()


@pytest.mark.asyncio
async def test_conversation_repository(test_db: DatabaseManager) -> None:
    """Verify ConversationRepository add, get, limit, and clear operations."""
    repo = ConversationRepository(test_db)
    session_id = "session_test_1"

    id1 = await repo.add_message(session_id, user_id=101, role="user", content="Hello Aru")
    id2 = await repo.add_message(
        session_id,
        user_id=101,
        role="assistant",
        content="Hello Boss!",
        metadata={"tokens": 15},
    )

    assert id1 > 0
    assert id2 > id1

    history = await repo.get_history(session_id, limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello Aru"
    assert history[1]["role"] == "assistant"
    assert history[1]["metadata"]["tokens"] == 15

    assert await repo.count(session_id) == 2
    cleared = await repo.clear_history(session_id)
    assert cleared == 2
    assert await repo.count(session_id) == 0


@pytest.mark.asyncio
async def test_memory_repository_and_fts(test_db: DatabaseManager) -> None:
    """Verify MemoryRepository upsert, FTS search, and category listing."""
    repo = MemoryRepository(test_db)

    # 1. Store memories
    await repo.store(
        key="boss_drink",
        content="Boss prefers green tea without sugar",
        category="preference",
        tags="drink,tea",
    )
    await repo.store(
        key="project_deadline",
        content="The ARU AI V4 deadline is next week",
        category="project",
        tags="work,v4",
    )

    assert await repo.count() == 2

    # 2. Get by key
    item = await repo.get_by_key("boss_drink")
    assert item is not None
    assert "green tea" in item["content"]

    # 3. FTS Search
    tea_results = await repo.search("green tea")
    assert len(tea_results) >= 1
    assert tea_results[0]["key"] == "boss_drink"

    # Category search
    proj_results = await repo.search("V4", category="project")
    assert len(proj_results) >= 1
    assert proj_results[0]["key"] == "project_deadline"

    # 4. Upsert
    await repo.store(
        key="boss_drink",
        content="Boss prefers black coffee in the morning",
        category="preference",
    )
    updated = await repo.get_by_key("boss_drink")
    assert updated is not None
    assert "black coffee" in updated["content"]
    assert await repo.count() == 2

    # 5. Delete
    assert await repo.delete_by_key("boss_drink") is True
    assert await repo.get_by_key("boss_drink") is None


@pytest.mark.asyncio
async def test_task_repository(test_db: DatabaseManager) -> None:
    """Verify TaskRepository CRUD and status updates."""
    repo = TaskRepository(test_db)

    tid = await repo.create(
        title="Refactor Brain Layer",
        description="Build LLM Router",
        priority="high",
        due_date="2026-10-20",
    )
    assert tid > 0

    task = await repo.get_by_id(tid)
    assert task is not None
    assert task["status"] == "pending"
    assert task["priority"] == "high"

    # Update status
    assert await repo.update_status(tid, "in_progress") is True
    updated = await repo.get_by_id(tid)
    assert updated["status"] == "in_progress"

    # List
    tasks = await repo.list_tasks(status="in_progress")
    assert len(tasks) == 1
    assert tasks[0]["id"] == tid

    # Delete
    assert await repo.delete(tid) is True
    assert await repo.get_by_id(tid) is None


@pytest.mark.asyncio
async def test_anti_spam_repository(test_db: DatabaseManager) -> None:
    """Verify AntiSpamRepository cooldowns and whitelists."""
    repo = AntiSpamRepository(test_db)
    user_id = 999001

    assert await repo.is_cooled_down(user_id) is False

    # Set cooldown for 1 hour in the future
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.set_cooldown(user_id, cooldown_until=future_time, reason="Rate limit exceeded")

    assert await repo.is_cooled_down(user_id) is True
    record = await repo.get_cooldown(user_id)
    assert record is not None
    assert record["reason"] == "Rate limit exceeded"

    # Clear cooldown
    assert await repo.clear_cooldown(user_id) is True
    assert await repo.is_cooled_down(user_id) is False

    # Spam event
    event_id = await repo.record_spam_event(user_id, "flood_wait", "10 msgs in 2s")
    assert event_id > 0

    # Whitelist
    assert await repo.is_whitelisted(user_id) is False
    assert await repo.add_to_whitelist(user_id, notes="Approved VIP") is True
    assert await repo.is_whitelisted(user_id) is True
    assert await repo.remove_from_whitelist(user_id) is True
    assert await repo.is_whitelisted(user_id) is False


@pytest.mark.asyncio
async def test_database_di_registration(tmp_path: Path) -> None:
    """Verify DatabaseManager and repositories resolve cleanly via DI container."""
    container = Container()
    db_file = tmp_path / "di_aru_v4.db"
    db_manager = DatabaseManager(db_file)

    container.register_instance(DatabaseManager, db_manager)
    container.register_singleton(ConversationRepository)
    container.register_singleton(MemoryRepository)

    conv_repo = container.resolve(ConversationRepository)
    mem_repo = container.resolve(MemoryRepository)

    assert isinstance(conv_repo, ConversationRepository)
    assert isinstance(mem_repo, MemoryRepository)
    assert conv_repo.db is db_manager
    assert mem_repo.db is db_manager
