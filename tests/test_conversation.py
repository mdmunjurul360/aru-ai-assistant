"""Tests for persistent conversation history storage."""

from __future__ import annotations

from modules.conversation import ConversationHistoryStore


def test_conversation_add_and_retrieve(tmp_db_path: str) -> None:
    store = ConversationHistoryStore(db_path=tmp_db_path)

    store.add_message(1001, "user", "Hello Aru!")
    store.add_message(1001, "assistant", "Hello Boss, how can I help you today?")
    store.add_message(1001, "user", "What's on my schedule?")

    history = store.get_history(1001)
    assert len(history) == 3
    assert history[0] == {"role": "user", "content": "Hello Aru!"}
    assert history[1] == {"role": "assistant", "content": "Hello Boss, how can I help you today?"}
    assert history[2] == {"role": "user", "content": "What's on my schedule?"}


def test_conversation_persistence_across_instances(tmp_db_path: str) -> None:
    store1 = ConversationHistoryStore(db_path=tmp_db_path)
    store1.add_message(2002, "user", "Persistent message")
    store1.add_message(2002, "assistant", "Stored in SQLite")

    # Simulate restart by creating a new instance pointing to the same DB
    store2 = ConversationHistoryStore(db_path=tmp_db_path)
    history = store2.get_history(2002)

    assert len(history) == 2
    assert history[0]["content"] == "Persistent message"
    assert history[1]["content"] == "Stored in SQLite"


def test_conversation_limit_chronological_order(tmp_db_path: str) -> None:
    store = ConversationHistoryStore(db_path=tmp_db_path)

    # Insert 25 messages
    for i in range(1, 26):
        role = "user" if i % 2 != 0 else "assistant"
        store.add_message(3003, role, f"Message {i}")

    # Request only latest 5
    latest_5 = store.get_history(3003, limit=5)
    assert len(latest_5) == 5
    # Must be in chronological order: Message 21, 22, 23, 24, 25
    assert latest_5[0]["content"] == "Message 21"
    assert latest_5[-1]["content"] == "Message 25"


def test_conversation_chat_isolation(tmp_db_path: str) -> None:
    store = ConversationHistoryStore(db_path=tmp_db_path)

    store.add_message(4001, "user", "Chat 1 message")
    store.add_message(4002, "user", "Chat 2 message")

    history1 = store.get_history(4001)
    history2 = store.get_history(4002)

    assert len(history1) == 1
    assert history1[0]["content"] == "Chat 1 message"
    assert len(history2) == 1
    assert history2[0]["content"] == "Chat 2 message"


def test_conversation_clear_and_count(tmp_db_path: str) -> None:
    store = ConversationHistoryStore(db_path=tmp_db_path)

    store.add_message(5001, "user", "Msg A")
    store.add_message(5001, "assistant", "Msg B")
    store.add_message(5002, "user", "Other chat Msg")

    assert store.count(5001) == 2
    assert store.count(5002) == 1
    assert store.count() == 3

    cleared = store.clear_history(5001)
    assert cleared == 2
    assert store.count(5001) == 0
    assert store.count(5002) == 1
    assert store.count() == 1
