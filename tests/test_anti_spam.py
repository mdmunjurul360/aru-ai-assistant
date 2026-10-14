"""Tests for AntiSpamManager in modules/anti_spam.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from modules.anti_spam import AntiSpamManager, COOLDOWN_HOURS, IGNORE_THRESHOLD


def test_anti_spam_boss_always_allowed(tmp_db_path: str):
    manager = AntiSpamManager(db_path=tmp_db_path)
    allowed, reason = manager.should_reply(7393294803, is_boss=True)
    assert allowed is True
    assert reason == "boss"


def test_anti_spam_first_reply(tmp_db_path: str):
    manager = AntiSpamManager(db_path=tmp_db_path)
    user_id = 999111222
    allowed, reason = manager.should_reply(user_id, is_boss=False)
    assert allowed is True
    assert reason == "first_reply"


def test_anti_spam_cooldown_active(tmp_db_path: str):
    manager = AntiSpamManager(db_path=tmp_db_path)
    user_id = 999111222

    # Record reply sent
    manager.record_reply(user_id, is_boss=False)

    # Subsequent check within cooldown
    allowed, reason = manager.should_reply(user_id, is_boss=False)
    assert allowed is False
    assert reason == "cooldown_active"


def test_anti_spam_ignored_message_count(tmp_db_path: str):
    manager = AntiSpamManager(db_path=tmp_db_path)
    user_id = 999111222
    manager.record_reply(user_id, is_boss=False)

    for _ in range(5):
        manager.record_ignored_message(user_id)

    info = manager.get_cooldown_info(user_id)
    assert info is not None
    assert info.message_count == 5


def test_anti_spam_spam_threshold(tmp_db_path: str):
    manager = AntiSpamManager(db_path=tmp_db_path)
    user_id = 999111222
    manager.record_reply(user_id, is_boss=False)

    # Exceed ignore threshold
    with manager._conn() as conn:
        conn.execute(
            "UPDATE user_cooldowns SET message_count = ? WHERE user_id = ?",
            (IGNORE_THRESHOLD, user_id),
        )

    allowed, reason = manager.should_reply(user_id, is_boss=False)
    assert allowed is False
    assert reason == "spam_threshold"


def test_anti_spam_cooldown_expired(tmp_db_path: str):
    manager = AntiSpamManager(db_path=tmp_db_path)
    user_id = 999111222
    past_time = (datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS + 1)).isoformat()

    with manager._conn() as conn:
        conn.execute(
            """
            INSERT INTO user_cooldowns (user_id, last_reply_at, message_count, created_at, updated_at)
            VALUES (?, ?, 10, ?, ?)
            """,
            (user_id, past_time, past_time, past_time),
        )

    allowed, reason = manager.should_reply(user_id, is_boss=False)
    assert allowed is True
    assert reason == "cooldown_expired"


def test_anti_spam_clear_cooldown(tmp_db_path: str):
    manager = AntiSpamManager(db_path=tmp_db_path)
    user_id = 999111222
    manager.record_reply(user_id, is_boss=False)
    assert manager.get_cooldown_info(user_id) is not None

    manager.clear_cooldown(user_id)
    assert manager.get_cooldown_info(user_id) is None
