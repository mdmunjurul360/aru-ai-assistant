"""Tests for database maintenance jobs and scheduler integration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from modules.activity_log import ActivityLogger
from modules.anti_spam import AntiSpamManager
from modules.maintenance import DatabaseMaintenance
from modules.memory import MemoryStore
from modules.scheduler import AruScheduler
from modules.tasks import TaskManager


def test_cleanup_old_activity_logs(tmp_db_path: str) -> None:
    logger = ActivityLogger(db_path=tmp_db_path)
    logger.log("system", "RECENT_ACTION", "Recent log entry")

    # Manually insert backdated entries older than 30 days
    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    with sqlite3.connect(tmp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO activity_logs (module, action, detail, level, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("system", "OLD_ACTION_1", "Old log 1", "info", old_date),
        )
        conn.execute(
            """
            INSERT INTO activity_logs (module, action, detail, level, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("system", "OLD_ACTION_2", "Old log 2", "info", old_date),
        )
        conn.commit()

    assert logger.count() == 3

    maintenance = DatabaseMaintenance(db_path=tmp_db_path)
    pruned = maintenance.cleanup_activity_logs(days=30)
    assert pruned == 2
    assert logger.count() == 1


def test_cleanup_expired_cooldowns(tmp_db_path: str) -> None:
    anti_spam = AntiSpamManager(db_path=tmp_db_path)
    anti_spam.record_reply(99901, is_boss=False)

    # Insert backdated cooldown older than 72 hours
    old_date = (datetime.now(timezone.utc) - timedelta(hours=96)).isoformat()
    with sqlite3.connect(tmp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_cooldowns (user_id, last_reply_at, message_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (99902, old_date, 5, old_date, old_date),
        )
        conn.commit()

    maintenance = DatabaseMaintenance(db_path=tmp_db_path)
    pruned = maintenance.cleanup_expired_cooldowns(hours=72)
    assert pruned == 1

    # Recent cooldown for 99901 should still exist
    assert anti_spam.get_cooldown_info(99901) is not None
    # Expired cooldown for 99902 should be gone
    assert anti_spam.get_cooldown_info(99902) is None


def test_wal_checkpoint_and_vacuum(tmp_db_path: str) -> None:
    maintenance = DatabaseMaintenance(db_path=tmp_db_path)

    # Initialize tables
    MemoryStore(db_path=tmp_db_path)

    checkpoint_info = maintenance.wal_checkpoint("TRUNCATE")
    assert "mode=TRUNCATE" in checkpoint_info

    vacuum_ok = maintenance.vacuum_database()
    assert vacuum_ok is True


def test_analyze_database(tmp_db_path: str) -> None:
    maintenance = DatabaseMaintenance(db_path=tmp_db_path)
    MemoryStore(db_path=tmp_db_path)

    analyze_ok = maintenance.analyze_database()
    assert analyze_ok is True


def test_run_full_maintenance_summary(tmp_db_path: str) -> None:
    ActivityLogger(db_path=tmp_db_path)
    AntiSpamManager(db_path=tmp_db_path)
    maintenance = DatabaseMaintenance(db_path=tmp_db_path)

    summary = maintenance.run_full_maintenance()
    assert isinstance(summary, dict)
    assert "timestamp" in summary
    assert "logs_pruned" in summary
    assert "cooldowns_pruned" in summary
    assert "cache_pruned" in summary
    assert "wal_checkpoint" in summary
    assert summary["vacuum"] is True
    assert summary["analyze"] is True


def test_scheduler_maintenance_integration(tmp_db_path: str) -> None:
    async def mock_send(msg: str) -> None:
        pass

    tasks = TaskManager(db_path=tmp_db_path)
    mem = MemoryStore(db_path=tmp_db_path)
    maintenance = DatabaseMaintenance(db_path=tmp_db_path)

    scheduler = AruScheduler(
        send_to_boss=mock_send,
        task_manager=tasks,
        memory_store=mem,
        maintenance=maintenance,
    )

    report = scheduler.run_maintenance_now()
    assert isinstance(report, dict)
    assert report["vacuum"] is True
    assert report["analyze"] is True
