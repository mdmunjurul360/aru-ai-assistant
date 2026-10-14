"""ARU AI V4 Logging & Observability System."""

from __future__ import annotations

from aru.core.logging.context import (
    correlation_scope,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from aru.core.logging.formatters import ConsoleFormatter, JsonFormatter
from aru.core.logging.handlers import (
    create_console_handler,
    create_rotating_file_handler,
)
from aru.core.logging.service import (
    ILogger,
    StructuredLogger,
    setup_v4_logging,
)

__all__ = [
    "ConsoleFormatter",
    "ILogger",
    "JsonFormatter",
    "StructuredLogger",
    "correlation_scope",
    "create_console_handler",
    "create_rotating_file_handler",
    "get_correlation_id",
    "reset_correlation_id",
    "set_correlation_id",
    "setup_v4_logging",
]
