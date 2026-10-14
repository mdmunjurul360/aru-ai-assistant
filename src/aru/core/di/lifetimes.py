"""Service lifetime definitions for Dependency Injection."""

from __future__ import annotations

from enum import Enum, auto


class Lifetime(Enum):
    """Lifetime of registered services within the container."""

    SINGLETON = auto()
    TRANSIENT = auto()
    INSTANCE = auto()
