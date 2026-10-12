"""Tests for authentication and authorization in modules/auth.py."""

from __future__ import annotations

from modules.auth import (
    get_sender_id,
    is_boss,
    unauthorized_message,
    verify_secret_code,
    verify_sender,
)
from modules.config import BOSS_TELEGRAM_ID


class MockSender:
    def __init__(self, user_id: int):
        self.id = user_id


class MockSenderAlt:
    def __init__(self, sender_id: int):
        self.sender_id = sender_id


def test_get_sender_id():
    assert get_sender_id(None) is None
    assert get_sender_id(12345) == 12345
    assert get_sender_id(MockSender(998877)) == 998877
    assert get_sender_id(MockSenderAlt(445566)) == 445566


def test_is_boss():
    boss_id = BOSS_TELEGRAM_ID
    assert is_boss(boss_id) is True
    assert is_boss(boss_id + 1) is False
    assert is_boss(None) is False
    assert is_boss(0) is False


def test_verify_sender_authorized():
    boss_id = BOSS_TELEGRAM_ID
    auth, uid = verify_sender(MockSender(boss_id))
    assert auth is True
    assert uid == boss_id


def test_verify_sender_unauthorized():
    auth, uid = verify_sender(MockSender(111222333))
    assert auth is False
    assert uid == 111222333


def test_unauthorized_message():
    msg = unauthorized_message()
    assert isinstance(msg, str)
    assert len(msg) > 0
    assert "Aru AI" in msg or "মঞ্জুরুল" in msg


def test_verify_secret_code():
    from modules import config
    assert verify_secret_code(config.SECRET_CODE) is True
    assert verify_secret_code("DefinitelyWrongCode123456") is False
    assert verify_secret_code("") is False
