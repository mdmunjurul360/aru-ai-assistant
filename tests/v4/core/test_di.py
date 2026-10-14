"""Unit tests for Phase 3: Dependency Injection Container."""

from __future__ import annotations

import pytest

from aru.core.di import (
    CircularDependencyError,
    Container,
    ResolutionError,
    ServiceNotFoundError,
)


class DummyDatabase:
    def __init__(self) -> None:
        self.connected = True


class DummyCache:
    def __init__(self, db: DummyDatabase) -> None:
        self.db = db


class DummyService:
    def __init__(self, cache: DummyCache) -> None:
        self.cache = cache


class ServiceWithDefault:
    def __init__(self, db: DummyDatabase, timeout: float = 30.0) -> None:
        self.db = db
        self.timeout = timeout


# Circular dependency classes
class CircularA:
    def __init__(self, b: CircularB) -> None:
        self.b = b


class CircularB:
    def __init__(self, a: CircularA) -> None:
        self.a = a


class SelfCircular:
    def __init__(self, s: SelfCircular) -> None:
        self.s = s


def test_singleton_lifetime() -> None:
    """Verify singleton is instantiated once and cached."""
    container = Container()
    container.register_singleton(DummyDatabase)

    db1 = container.resolve(DummyDatabase)
    db2 = container.resolve(DummyDatabase)

    assert isinstance(db1, DummyDatabase)
    assert db1 is db2


def test_transient_lifetime() -> None:
    """Verify transient creates fresh instances per resolve."""
    container = Container()
    container.register_transient(DummyDatabase)

    db1 = container.resolve(DummyDatabase)
    db2 = container.resolve(DummyDatabase)

    assert isinstance(db1, DummyDatabase)
    assert db1 is not db2


def test_register_instance() -> None:
    """Verify pre-instantiated instance registration."""
    container = Container()
    instance = DummyDatabase()
    container.register_instance(DummyDatabase, instance)

    resolved = container.resolve(DummyDatabase)
    assert resolved is instance


def test_nested_dependency_resolution() -> None:
    """Verify multi-level dependency tree resolution: Service -> Cache -> Database."""
    container = Container()
    container.register_singleton(DummyDatabase)
    container.register_singleton(DummyCache)
    container.register_transient(DummyService)

    svc = container.resolve(DummyService)
    assert isinstance(svc, DummyService)
    assert isinstance(svc.cache, DummyCache)
    assert isinstance(svc.cache.db, DummyDatabase)
    assert svc.cache.db.connected is True


def test_parameter_with_default_value() -> None:
    """Verify unprovided parameters with defaults use their default value."""
    container = Container()
    container.register_singleton(DummyDatabase)
    container.register_transient(ServiceWithDefault)

    svc = container.resolve(ServiceWithDefault)
    assert svc.timeout == 30.0
    assert svc.db is not None


def test_circular_dependency_detection() -> None:
    """Verify CircularDependencyError is raised when cycle exists (A -> B -> A)."""
    container = Container()
    container.register_transient(CircularA)
    container.register_transient(CircularB)

    with pytest.raises(CircularDependencyError) as exc_info:
        container.resolve(CircularA)

    assert "Circular dependency detected" in str(exc_info.value)
    assert "CircularA" in str(exc_info.value)
    assert "CircularB" in str(exc_info.value)


def test_self_circular_dependency() -> None:
    """Verify CircularDependencyError on direct self-reference."""
    container = Container()
    container.register_transient(SelfCircular)

    with pytest.raises(CircularDependencyError):
        container.resolve(SelfCircular)


def test_service_not_found() -> None:
    """Verify ServiceNotFoundError when resolving unregistered abstract or primitive."""
    container = Container()

    class IUnregisteredInterface:
        pass

    with pytest.raises(ServiceNotFoundError):
        container.resolve(IUnregisteredInterface)


def test_factory_function_with_di() -> None:
    """Verify factory functions have their dependencies resolved and passed."""
    container = Container()
    container.register_singleton(DummyDatabase)

    def create_custom_cache(db: DummyDatabase) -> DummyCache:
        return DummyCache(db=db)

    container.register_singleton(DummyCache, create_custom_cache)

    cache = container.resolve(DummyCache)
    assert isinstance(cache, DummyCache)
    assert cache.db is container.resolve(DummyDatabase)
