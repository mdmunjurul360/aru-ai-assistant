"""Contextual execution tracking and correlation IDs for ARU AI V4."""

from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from typing import Generator

_CORRELATION_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def get_correlation_id() -> str:
    """Retrieve current correlation ID from context or return empty string."""
    return _CORRELATION_ID_VAR.get()


def set_correlation_id(correlation_id: str) -> contextvars.Token[str]:
    """Explicitly set correlation ID in current asynchronous context."""
    return _CORRELATION_ID_VAR.set(correlation_id)


def reset_correlation_id(token: contextvars.Token[str]) -> None:
    """Reset correlation ID using token returned by set_correlation_id."""
    _CORRELATION_ID_VAR.reset(token)


@contextmanager
def correlation_scope(correlation_id: str | None = None) -> Generator[str, None, None]:
    """
    Context manager that establishes a correlation scope.
    If no correlation_id is provided, a new random identifier is generated.
    """
    cid = correlation_id or uuid.uuid4().hex[:12]
    token = _CORRELATION_ID_VAR.set(cid)
    try:
        yield cid
    finally:
        _CORRELATION_ID_VAR.reset(token)
