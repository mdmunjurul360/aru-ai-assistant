"""Tests for command parsers in modules/commands.py."""

from __future__ import annotations

from modules.anti_spam import AntiSpamManager
from modules.commands import (
    handle_cooldown_command,
    handle_help_command,
    handle_memory_command,
    handle_status_command,
)
from modules.memory import MemoryStore


def test_handle_help_command():
    assert handle_help_command("/help") is not None
    assert handle_help_command("/start") is not None
    assert handle_help_command("/aru") is not None
    assert handle_help_command("/other") is None


def test_handle_status_command():
    status = handle_status_command(
        "/status",
        telegram_ok=True,
        groq_ok=True,
        memory_count=5,
        pending_tasks=2,
        voice_ok=True,
        activity_count=10,
    )
    assert status is not None
    assert "Telegram: ✅" in status
    assert "Groq AI: ✅" in status
    assert "Memories: 5" in status
    assert "Pending tasks: 2" in status


def test_handle_cooldown_command(tmp_db_path: str):
    anti_spam = AntiSpamManager(db_path=tmp_db_path)
    user_id = 123456789

    # No cooldown active
    res1 = handle_cooldown_command("/cooldown", anti_spam, user_id)
    assert res1 is not None
    assert "কোনো কুলডাউন সক্রিয় নেই" in res1

    # Active cooldown
    anti_spam.record_reply(user_id, is_boss=False)
    res2 = handle_cooldown_command("/cooldown", anti_spam, user_id)
    assert res2 is not None
    assert "User ID: `123456789`" in res2


def test_handle_memory_command(tmp_db_path: str):
    store = MemoryStore(db_path=tmp_db_path)

    # Save
    save_res = handle_memory_command("/memory save goal | Build System | Deploy Sprint 1", store)
    assert save_res is not None
    assert "মেমোরি সংরক্ষিত" in save_res

    # List
    list_res = handle_memory_command("/memory list", store)
    assert list_res is not None
    assert "Build System" in list_res

    # Search
    search_res = handle_memory_command("/memory search Build", store)
    assert search_res is not None
    assert "Build System" in search_res
