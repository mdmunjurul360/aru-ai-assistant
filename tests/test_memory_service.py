"""Tests for MemoryService abstraction layer."""

from __future__ import annotations

from modules.memory_service import MemoryService


def test_memory_service_conversation_lifecycle(tmp_db_path: str) -> None:
    service = MemoryService(db_path=tmp_db_path)

    service.record_user_message(101, "Hello assistant")
    service.record_assistant_message(101, "Hello boss!")
    service.record_interaction(101, "What is my goal?", "Your goal is to build Aru AI.")

    context = service.get_conversation_context(101)
    assert len(context) == 4
    assert context[0] == {"role": "user", "content": "Hello assistant"}
    assert context[1] == {"role": "assistant", "content": "Hello boss!"}
    assert context[2] == {"role": "user", "content": "What is my goal?"}
    assert context[3] == {"role": "assistant", "content": "Your goal is to build Aru AI."}

    cleared = service.clear_conversation(101)
    assert cleared == 4
    assert len(service.get_conversation_context(101)) == 0


def test_memory_service_prompt_context_synthesis(tmp_db_path: str) -> None:
    service = MemoryService(db_path=tmp_db_path)

    service.save_preference("Diet", "Boss drinks black coffee without sugar")
    service.save_fact("Location", "Boss is currently located in Dhaka")

    context_str = service.build_context_for_prompt("What coffee should I make?")
    assert "Boss drinks black coffee" in context_str


def test_memory_service_logical_types(tmp_db_path: str) -> None:
    service = MemoryService(db_path=tmp_db_path)

    f = service.save_fact("Python version", "3.12")
    p = service.save_preference("Editor", "Cursor IDE")
    g = service.save_goal("Sprint 2", "Context Persistence")
    proj = service.save_project("Aru AI", "Personal Telegram assistant")

    assert f.category == "fact"
    assert p.category == "preference"
    assert g.category == "goal"
    assert proj.category == "project"

    facts = service.get_facts()
    assert len(facts) == 1
    assert facts[0].title == "Python version"

    prefs = service.get_preferences()
    assert len(prefs) == 1
    assert prefs[0].title == "Editor"

    goals = service.get_goals()
    assert len(goals) == 1
    assert goals[0].title == "Sprint 2"

    projects = service.get_projects()
    assert len(projects) == 1
    assert projects[0].title == "Aru AI"


def test_memory_service_search_and_semantic_hook(tmp_db_path: str) -> None:
    service = MemoryService(db_path=tmp_db_path)

    service.save_memory("Cloud Architecture", "Deployed on Google Cloud Run", category="fact")
    service.save_memory("Database Engine", "SQLite in WAL mode", category="fact")

    fts_results = service.search("Cloud Run")
    assert len(fts_results) == 1
    assert fts_results[0].title == "Cloud Architecture"

    semantic_results = service.search_semantic("Cloud Run")
    assert len(semantic_results) == 1
    assert semantic_results[0].title == "Cloud Architecture"


def test_memory_service_crud_lifecycle(tmp_db_path: str) -> None:
    service = MemoryService(db_path=tmp_db_path)

    item = service.save_memory("Original Title", "Original Content", category="note")
    assert item.id > 0

    fetched = service.get(item.id)
    assert fetched is not None
    assert fetched.title == "Original Title"

    updated = service.update(item.id, title="Updated Title", content="Updated Content")
    assert updated is not None
    assert updated.title == "Updated Title"

    all_items = service.list_all(category="note")
    assert len(all_items) == 1

    deleted = service.delete(item.id)
    assert deleted is True
    assert service.get(item.id) is None
