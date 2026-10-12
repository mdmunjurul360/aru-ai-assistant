"""Tests for centralized SQLite database management in modules/db.py."""

from __future__ import annotations

import sqlite3
import pytest

from modules.db import ensure_db_ready, get_db_connection


def test_db_connection_wal_mode(tmp_db_path: str):
    with get_db_connection(tmp_db_path) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    assert str(journal_mode).upper() == "WAL"
    assert busy_timeout >= 5000
    assert foreign_keys == 1


def test_db_transaction_commit(tmp_db_path: str):
    with get_db_connection(tmp_db_path) as conn:
        conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test_table (name) VALUES ('alpha')")

    with get_db_connection(tmp_db_path) as conn:
        row = conn.execute("SELECT name FROM test_table WHERE id = 1").fetchone()
        assert row is not None
        assert row["name"] == "alpha"


def test_db_transaction_rollback_on_error(tmp_db_path: str):
    with get_db_connection(tmp_db_path) as conn:
        conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test_table (name) VALUES ('first')")

    with pytest.raises(ValueError):
        with get_db_connection(tmp_db_path) as conn:
            conn.execute("INSERT INTO test_table (name) VALUES ('second')")
            raise ValueError("Forced failure")

    with get_db_connection(tmp_db_path) as conn:
        rows = conn.execute("SELECT * FROM test_table").fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "first"


def test_ensure_db_ready(tmp_db_path: str):
    mode = ensure_db_ready(tmp_db_path)
    assert mode == "WAL"
