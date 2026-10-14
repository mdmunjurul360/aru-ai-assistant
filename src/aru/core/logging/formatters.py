"""Log record formatters for JSON and console output in ARU AI V4."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from aru.core.logging.context import get_correlation_id

_STANDARD_LOGRECORD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Formats log records as structured, single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        # Resolve correlation ID (prefer explicit attribute on record, fallback to context)
        corr_id = getattr(record, "correlation_id", None) or get_correlation_id() or None

        # Build ISO 8601 UTC timestamp
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        iso_time = dt.isoformat()

        log_data: dict[str, Any] = {
            "timestamp": iso_time,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": corr_id,
            "module": record.module,
            "line": record.lineno,
            "function": record.funcName,
        }

        # Extract extra fields passed via extra={...}
        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _STANDARD_LOGRECORD_ATTRS and k != "correlation_id"
        }
        if extra_fields:
            log_data["extra"] = extra_fields

        # Format exception if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console log formatter with correlation ID and optional colors."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[1;31m",  # Bold Red
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True) -> None:
        super().__init__()
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        corr_id = getattr(record, "correlation_id", None) or get_correlation_id()
        corr_str = f" [corr:{corr_id}]" if corr_id else ""

        dt = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level_str = record.levelname.ljust(8)

        if self.use_colors and record.levelname in self.COLORS:
            level_fmt = f"{self.COLORS[record.levelname]}{level_str}{self.RESET}"
        else:
            level_fmt = level_str

        msg = record.getMessage()
        output = f"[{dt}] [{level_fmt}]{corr_str} [{record.name}]: {msg}"

        if record.exc_info:
            output += f"\n{self.formatException(record.exc_info)}"

        return output
