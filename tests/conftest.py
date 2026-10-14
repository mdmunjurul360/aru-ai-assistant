"""Pytest fixtures for isolated testing."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator

import pytest

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    """Provide a path to a fresh temporary SQLite database."""
    db_file = tmp_path / "test_memory.db"
    return str(db_file)


@pytest.fixture(autouse=True)
def test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up safe mock environment variables for tests."""
    monkeypatch.setenv("TG_API_ID", "12345678")
    monkeypatch.setenv("TG_API_HASH", "mock_telegram_hash_abc123")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_mock_groq_api_key_test_123")
    monkeypatch.setenv("BOSS_TELEGRAM_ID", "7393294803")
    monkeypatch.setenv("SECRET_CODE", "TestSecret123")
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
