"""Dependency Injection Container for ARU AI V4."""

from __future__ import annotations

import inspect
from typing import Any, Callable, TypeVar, get_type_hints

from aru.core.di.exceptions import (
    CircularDependencyError,
    ResolutionError,
    ServiceNotFoundError,
)
from aru.core.di.lifetimes import Lifetime

T = TypeVar("T")


def _type_name(t: Any) -> str:
    """Return human-readable name of type or string identifier."""
    if isinstance(t, str):
        return t
    return getattr(t, "__name__", str(t))


class _ServiceDescriptor:
    """Internal metadata descriptor for a registered service."""

    def __init__(
        self,
        service_type: type,
        lifetime: Lifetime,
        factory_or_impl: type | Callable[..., Any],
        instance: Any = None,
    ) -> None:
        self.service_type = service_type
        self.lifetime = lifetime
        self.factory_or_impl = factory_or_impl
        self.instance = instance


class Container:
    """
    Lightweight, thread-safe Inversion of Control (IoC) service container.
    Supports Singleton, Transient, and Pre-instantiated Instance lifetimes,
    constructor injection via type hints, and circular dependency detection.
    """

    def __init__(self) -> None:
        self._registry: dict[type, _ServiceDescriptor] = {}
        self._name_map: dict[str, type] = {}
        self._resolution_stack: list[type] = []

    def register_instance(self, service_type: type[T], instance: T) -> Container:
        """Register a pre-built instance as a singleton."""
        if not isinstance(instance, service_type):
            raise ResolutionError(
                f"Instance of type {type(instance).__name__} does not match {_type_name(service_type)}"
            )
        self._registry[service_type] = _ServiceDescriptor(
            service_type=service_type,
            lifetime=Lifetime.INSTANCE,
            factory_or_impl=lambda: instance,
            instance=instance,
        )
        self._name_map[service_type.__name__] = service_type
        return self

    def register_singleton(
        self,
        service_type: type[T],
        factory_or_impl: type[T] | Callable[..., T] | None = None,
    ) -> Container:
        """Register a service with Singleton lifetime (instantiated once, cached)."""
        impl = factory_or_impl if factory_or_impl is not None else service_type
        self._registry[service_type] = _ServiceDescriptor(
            service_type=service_type,
            lifetime=Lifetime.SINGLETON,
            factory_or_impl=impl,
            instance=None,
        )
        self._name_map[service_type.__name__] = service_type
        return self

    def register_transient(
        self,
        service_type: type[T],
        factory_or_impl: type[T] | Callable[..., T] | None = None,
    ) -> Container:
        """Register a service with Transient lifetime (fresh instance per resolution)."""
        impl = factory_or_impl if factory_or_impl is not None else service_type
        self._registry[service_type] = _ServiceDescriptor(
            service_type=service_type,
            lifetime=Lifetime.TRANSIENT,
            factory_or_impl=impl,
            instance=None,
        )
        self._name_map[service_type.__name__] = service_type
        return self

    def has(self, service_type: type | str) -> bool:
        """Check whether service_type is explicitly registered."""
        if isinstance(service_type, str):
            return service_type in self._name_map
        return service_type in self._registry

    def resolve(self, service_type: type[T] | str) -> T:
        """Resolve an instance of service_type according to its lifetime registration."""
        # Convert string identifier to type if needed
        real_type: type
        if isinstance(service_type, str):
            if service_type in self._name_map:
                real_type = self._name_map[service_type]
            else:
                raise ServiceNotFoundError(
                    f"Service '{service_type}' is not registered in the container."
                )
        else:
            real_type = service_type

        # Circular dependency check
        if real_type in self._resolution_stack:
            chain = " -> ".join(_type_name(t) for t in self._resolution_stack) + f" -> {_type_name(real_type)}"
            raise CircularDependencyError(f"Circular dependency detected: {chain}")

        descriptor = self._registry.get(real_type)
        if descriptor is None:
            raise ServiceNotFoundError(
                f"Service {_type_name(real_type)} is not registered in the container."
            )

        # Instance lifetime
        if descriptor.lifetime == Lifetime.INSTANCE:
            return descriptor.instance  # type: ignore[no-any-return]

        # Singleton lifetime: return cached instance if already created
        if descriptor.lifetime == Lifetime.SINGLETON and descriptor.instance is not None:
            return descriptor.instance  # type: ignore[no-any-return]

        # Instantiate service
        self._resolution_stack.append(real_type)
        try:
            created = self._instantiate(real_type, descriptor.factory_or_impl)
            if descriptor.lifetime == Lifetime.SINGLETON:
                descriptor.instance = created
            return created  # type: ignore[no-any-return]
        finally:
            self._resolution_stack.pop()

    def _instantiate(self, requested_type: type, factory_or_impl: type | Callable[..., Any]) -> Any:
        """Inspect dependencies and invoke constructor or factory."""
        call_target: Callable[..., Any]
        type_hints: dict[str, Any] = {}

        if inspect.isclass(factory_or_impl):
            init_func = getattr(factory_or_impl, "__init__")
            if init_func is object.__init__:
                return factory_or_impl()
            call_target = factory_or_impl
            sig = inspect.signature(init_func)
            params = list(sig.parameters.values())[1:]  # skip self
            try:
                type_hints = get_type_hints(init_func)
            except Exception:
                type_hints = getattr(init_func, "__annotations__", {})
        elif callable(factory_or_impl):
            call_target = factory_or_impl
            sig = inspect.signature(factory_or_impl)
            params = list(sig.parameters.values())
            try:
                type_hints = get_type_hints(factory_or_impl)
            except Exception:
                type_hints = getattr(factory_or_impl, "__annotations__", {})
        else:
            raise ResolutionError(
                f"Cannot resolve service {_type_name(requested_type)}: factory is not callable."
            )

        kwargs: dict[str, Any] = {}
        for param in params:
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue

            param_name = param.name
            has_default = param.default is not inspect.Parameter.empty

            # Prefer resolved type hint over raw annotation
            param_type = type_hints.get(param_name, param.annotation)

            if param_type is inspect.Parameter.empty:
                if has_default:
                    kwargs[param_name] = param.default
                    continue
                raise ResolutionError(
                    f"Parameter '{param_name}' on {_type_name(call_target)} has no type annotation and no default value."
                )

            # Try resolving parameter
            try:
                kwargs[param_name] = self.resolve(param_type)
            except (ServiceNotFoundError, ResolutionError):
                if has_default:
                    kwargs[param_name] = param.default
                else:
                    raise

        try:
            return call_target(**kwargs)
        except Exception as err:
            if isinstance(err, (CircularDependencyError, ServiceNotFoundError, ResolutionError)):
                raise
            raise ResolutionError(
                f"Failed to instantiate {_type_name(requested_type)}: {err}"
            ) from err

    def clear(self) -> None:
        """Clear all registered services and caches."""
        self._registry.clear()
        self._name_map.clear()
        self._resolution_stack.clear()
