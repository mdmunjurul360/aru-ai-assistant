"""Tests for SQLite FTS5 full-text search and memory synchronization."""

from __future__ import annotations

import sqlite3

from modules.memory import MemoryStore


def test_fts_virtual_table_and_triggers_created(tmp_db_path: str) -> None:
    store = MemoryStore(db_path=tmp_db_path)

    with sqlite3.connect(tmp_db_path) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "memories_fts" in tables

        triggers = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()]
        assert "memories_ai" in triggers
        assert "memories_ad" in triggers
        assert "memories_au" in triggers


def test_fts_sync_on_insert(tmp_db_path: str) -> None:
    store = MemoryStore(db_path=tmp_db_path)
    item = store.save(
        title="Python Async Architecture",
        content="Telethon and APScheduler operate concurrently under asyncio event loop",
        category="fact",
    )

    results = store.search("asyncio")
    assert len(results) >= 1
    assert any(r.id == item.id for r in results)


def test_fts_sync_on_update(tmp_db_path: str) -> None:
    store = MemoryStore(db_path=tmp_db_path)
    item = store.save(
        title="Server Architecture",
        content="Running on Frankfurt GCP region",
        category="fact",
    )

    # Initial search finds Frankfurt
    assert len(store.search("Frankfurt")) == 1

    # Update content to Singapore
    store.update(item.id, content="Migrated to Singapore AWS cluster")

    # Search for new content
    assert len(store.search("Singapore")) == 1
    # Search for old content should not match this record
    assert len(store.search("Frankfurt")) == 0


def test_fts_sync_on_delete(tmp_db_path: str) -> None:
    store = MemoryStore(db_path=tmp_db_path)
    item = store.save(
        title="Temporary Credentials",
        content="Secret temporary access token 987654321",
        category="fact",
    )

    assert len(store.search("987654321")) == 1

    deleted = store.delete(item.id)
    assert deleted is True

    assert len(store.search("987654321")) == 0


def test_fts_ranking_relevance(tmp_db_path: str) -> None:
    store = MemoryStore(db_path=tmp_db_path)

    # Item with keyword in title and content
    item_high = store.save(
        title="Machine Learning Strategy",
        content="Machine Learning pipeline architecture for personal AI",
        category="goal",
    )
    # Item with single mention in content
    item_low = store.save(
        title="Reading List",
        content="Read books about history and machine learning",
        category="preference",
    )

    results = store.search("Machine Learning")
    assert len(results) >= 2
    # Item with title + multiple mentions should rank higher
    assert results[0].id == item_high.id


def test_fts_search_with_category_filter(tmp_db_path: str) -> None:
    store = MemoryStore(db_path=tmp_db_path)

    store.save("Goal 1", "Finish Sprint 2 Context Persistence", category="goal")
    store.save("Note 1", "Sprint 2 Context Persistence discussion notes", category="note")

    results_goal = store.search("Persistence", category="goal")
    assert len(results_goal) == 1
    assert results_goal[0].category == "goal"

    results_all = store.search("Persistence")
    assert len(results_all) == 2


def test_fts_punctuation_and_special_character_safety(tmp_db_path: str) -> None:
    store = MemoryStore(db_path=tmp_db_path)

    store.save("Safe Search", "Handles quotes ' \" and dashes - / * @ safely", category="fact")

    # Queries containing characters that could break raw FTS syntax
    for query in ['"quotes"', "dashes - /", "safe*", "test OR AND NOT ("]:
        # Should execute safely without raising SQLite syntax errors
        results = store.search(query)
        assert isinstance(results, list)
