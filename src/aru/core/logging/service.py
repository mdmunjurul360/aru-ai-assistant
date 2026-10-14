"""Structured logging service and DI-injectable logger for ARU AI V4."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from aru.core.config.models import AppSettings
from aru.core.logging.context import get_correlation_id
from aru.core.logging.handlers import (
    create_console_handler,
    create_rotating_file_handler,
)


class ILogger(Protocol):
    """Protocol for injectable structured loggers."""

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def bind(self, **extra: Any) -> ILogger: ...


class StructuredLogger:
    """
    Thread-safe, contextual logger implementing ILogger.
    Injects correlation IDs automatically and supports field binding.
    """

    def __init__(
        self,
        name: str = "aru",
        bound_fields: dict[str, Any] | None = None,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._name = name
        self._bound_fields = dict(bound_fields) if bound_fields else {}

    @property
    def name(self) -> str:
        return self._name

    def bind(self, **extra: Any) -> StructuredLogger:
        """Create a new StructuredLogger child with additional bound fields."""
        new_fields = {**self._bound_fields, **extra}
        return StructuredLogger(name=self._name, bound_fields=new_fields)

    def _log(
        self,
        level: int,
        msg: str,
        args: tuple[Any, ...],
        exc_info: Any = None,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if not self._logger.isEnabledFor(level):
            return

        combined_extra = {**self._bound_fields}
        if extra:
            combined_extra.update(extra)

        # Inject correlation_id if not explicitly provided
        if "correlation_id" not in combined_extra:
            cid = get_correlation_id()
            if cid:
                combined_extra["correlation_id"] = cid

        self._logger.log(
            level,
            msg,
            *args,
            exc_info=exc_info,
            extra=combined_extra,
            **kwargs,
        )

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, msg, args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs["exc_info"] = True
        self._log(logging.ERROR, msg, args, **kwargs)


def setup_v4_logging(
    settings: AppSettings | None = None,
    log_file: Path | str | None = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    use_colors: bool = True,
) -> StructuredLogger:
    """
    Configure V4 logging hierarchy under the 'aru' namespace.
    Writes structured JSON logs to logs/aru_v4.log (or configured path)
    and clean human-readable logs to stdout.
    Never overwrites or interferes with V3's 'aru.log'.
    """
    root_v4 = logging.getLogger("aru")
    root_v4.setLevel(logging.DEBUG)

    # Remove existing handlers on 'aru' to prevent duplicates if re-invoked
    root_v4.handlers.clear()

    # Determine log file path (separate from V3 logs)
    if log_file:
        target_log_file = Path(log_file)
    elif settings:
        target_log_file = settings.system.log_file
    else:
        target_log_file = Path("logs/aru_v4.log")

    # Add rotating file handler
    file_handler = create_rotating_file_handler(
        log_file=target_log_file,
        level=file_level,
    )
    root_v4.addHandler(file_handler)

    # Add console handler
    console_handler = create_console_handler(
        level=console_level,
        use_colors=use_colors,
    )
    root_v4.addHandler(console_handler)

    # Prevent propagation to root logger if desired
    root_v4.propagate = False

    return StructuredLogger(name="aru")
