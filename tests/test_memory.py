"""Tests for MemoryStore in modules/memory.py."""

from __future__ import annotations

from modules.memory import MemoryStore


def test_memory_save_and_get(tmp_db_path: str):
    store = MemoryStore(db_path=tmp_db_path)
    item = store.save("Favorite Framework", "FastAPI is preferred for backends", category="preference")
    assert item.id == 1
    assert item.title == "Favorite Framework"
    assert item.category == "preference"

    fetched = store.get_by_id(item.id)
    assert fetched is not None
    assert fetched.content == "FastAPI is preferred for backends"


def test_memory_search(tmp_db_path: str):
    store = MemoryStore(db_path=tmp_db_path)
    store.save("Docker Setup", "Use compose for local development", category="project")
    store.save("Kubernetes Goal", "Learn Helm charts this quarter", category="goal")

    results = store.search("Docker")
    assert len(results) == 1
    assert results[0].title == "Docker Setup"

    results_all = store.search("development")
    assert len(results_all) == 1


def test_memory_list_all(tmp_db_path: str):
    store = MemoryStore(db_path=tmp_db_path)
    store.save("Goal 1", "Finish Sprint 1", category="goal")
    store.save("Goal 2", "Review Architecture", category="goal")
    store.save("Fact 1", "Server runs Ubuntu 24.04", category="fact")

    all_items = store.list_all()
    assert len(all_items) == 3

    goals = store.list_all(category="goal")
    assert len(goals) == 2


def test_memory_update_and_delete(tmp_db_path: str):
    store = MemoryStore(db_path=tmp_db_path)
    item = store.save("Initial Title", "Initial Content")

    updated = store.update(item.id, title="Updated Title", content="Updated Content")
    assert updated is not None
    assert updated.title == "Updated Title"
    assert updated.content == "Updated Content"

    deleted = store.delete(item.id)
    assert deleted is True
    assert store.get_by_id(item.id) is None


def test_memory_remember_parsing(tmp_db_path: str):
    store = MemoryStore(db_path=tmp_db_path)
    # Pipe syntax
    item1 = store.remember("goal | Launch App | Release MVP by Friday")
    assert item1.category == "goal"
    assert item1.title == "Launch App"
    assert item1.content == "Release MVP by Friday"

    # Plain text
    item2 = store.remember("Boss prefers dark mode everywhere")
    assert item2.category == "fact"
    assert "dark mode" in item2.title


def test_memory_context_for_ai(tmp_db_path: str):
    store = MemoryStore(db_path=tmp_db_path)
    store.save("Language", "Boss writes Python and Go", category="preference")
    ctx = store.context_for_ai("Tell me about Python")
    assert "Python and Go" in ctx


def test_memory_v2_commands(tmp_db_path: str):
    store = MemoryStore(db_path=tmp_db_path)
    res_remember = store.handle_v2_command("/remember Python is the main language")
    assert res_remember is not None
    assert "মনে রাখলাম" in res_remember

    res_memories = store.handle_v2_command("/memories")
    assert res_memories is not None
    assert "মেমোরি" in res_memories

    res_search = store.handle_v2_command("/searchmemory Python")
    assert res_search is not None
    assert "Python" in res_search
