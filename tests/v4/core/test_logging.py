"""Unit tests for Phase 4: Logging & Observability System."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import pytest

from aru.core.di import Container
from aru.core.logging import (
    ConsoleFormatter,
    ILogger,
    JsonFormatter,
    StructuredLogger,
    correlation_scope,
    create_rotating_file_handler,
    get_correlation_id,
    setup_v4_logging,
)


def test_correlation_id_scope() -> None:
    """Verify correlation_scope sets, nests, and restores correlation IDs."""
    assert get_correlation_id() == ""

    with correlation_scope("outer_123") as cid1:
        assert cid1 == "outer_123"
        assert get_correlation_id() == "outer_123"

        with correlation_scope("inner_456") as cid2:
            assert cid2 == "inner_456"
            assert get_correlation_id() == "inner_456"

        assert get_correlation_id() == "outer_123"

    assert get_correlation_id() == ""


@pytest.mark.asyncio
async def test_async_correlation_isolation() -> None:
    """Verify asynchronous tasks maintain their own correlation IDs without leakage."""
    async def task_worker(task_id: str) -> list[str]:
        records = []
        with correlation_scope(task_id):
            records.append(get_correlation_id())
            await asyncio.sleep(0.01)
            records.append(get_correlation_id())
        return records

    res1, res2 = await asyncio.gather(task_worker("task_alpha"), task_worker("task_beta"))
    assert res1 == ["task_alpha", "task_alpha"]
    assert res2 == ["task_beta", "task_beta"]


def test_json_formatter_structure() -> None:
    """Verify JsonFormatter outputs valid JSON with expected attributes."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="aru.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Test message with extra metadata",
        args=(),
        exc_info=None,
    )
    record.funcName = "test_func"

    with correlation_scope("trace_abc"):
        record.__dict__["custom_key"] = "custom_value"
        formatted = formatter.format(record)

    data = json.loads(formatted)
    assert data["level"] == "INFO"
    assert data["logger"] == "aru.test"
    assert data["message"] == "Test message with extra metadata"
    assert data["correlation_id"] == "trace_abc"
    assert data["line"] == 42
    assert data["extra"]["custom_key"] == "custom_value"
    assert "timestamp" in data


def test_console_formatter_output() -> None:
    """Verify ConsoleFormatter produces human-readable text."""
    formatter = ConsoleFormatter(use_colors=False)
    record = logging.LogRecord(
        name="aru.core",
        level=logging.WARNING,
        pathname="core.py",
        lineno=10,
        msg="Something unexpected",
        args=(),
        exc_info=None,
    )

    with correlation_scope("corr_999"):
        formatted = formatter.format(record)

    assert "[WARNING ]" in formatted
    assert "[corr:corr_999]" in formatted
    assert "[aru.core]: Something unexpected" in formatted


def test_rotating_file_handler_creation(tmp_path: Path) -> None:
    """Verify RotatingFileHandler writes json lines to file without error."""
    log_file = tmp_path / "sub" / "aru_v4.log"
    handler = create_rotating_file_handler(log_file=log_file, max_bytes=1024, backup_count=2)

    logger = logging.getLogger("aru.test_file")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    logger.info("Writing a sample line to V4 log file")
    handler.close()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Writing a sample line to V4 log file" in content
    # Verify valid JSON
    data = json.loads(content.strip())
    assert data["message"] == "Writing a sample line to V4 log file"


def test_structured_logger_binding() -> None:
    """Verify StructuredLogger bind() attaches metadata to child logger."""
    base_logger = StructuredLogger(name="aru.test_bind")
    bound_logger = base_logger.bind(user_id=12345, action="deposit")

    assert bound_logger._bound_fields == {"user_id": 12345, "action": "deposit"}


def test_di_container_logger_injection(tmp_path: Path) -> None:
    """Verify StructuredLogger integrates seamlessly into DI container."""
    container = Container()
    log_file = tmp_path / "aru_v4_di.log"
    logger = setup_v4_logging(log_file=log_file, use_colors=False)

    container.register_instance(StructuredLogger, logger)

    class OrderService:
        def __init__(self, log: StructuredLogger) -> None:
            self.log = log

    container.register_transient(OrderService)

    svc = container.resolve(OrderService)
    assert isinstance(svc, OrderService)
    assert svc.log is logger
