"""Log handler factories for rotating files and console output in ARU AI V4."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from aru.core.logging.formatters import ConsoleFormatter, JsonFormatter


def create_rotating_file_handler(
    log_file: Path | str,
    max_bytes: int = 10_485_760,  # 10 MB
    backup_count: int = 5,
    level: int = logging.DEBUG,
    formatter: logging.Formatter | None = None,
) -> RotatingFileHandler:
    """Create a thread-safe rotating file handler writing structured JSON."""
    file_path = Path(log_file).resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        filename=str(file_path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter or JsonFormatter())
    return handler


def create_console_handler(
    level: int = logging.INFO,
    formatter: logging.Formatter | None = None,
    stream: TextIO | None = None,
    use_colors: bool = True,
) -> logging.StreamHandler:
    """Create a stream handler for console output."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(formatter or ConsoleFormatter(use_colors=use_colors))
    return handler
