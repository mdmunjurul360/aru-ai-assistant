"""Exceptions for Dependency Injection container."""

from __future__ import annotations


class DIError(Exception):
    """Base exception for all dependency injection errors."""


class ServiceNotFoundError(DIError):
    """Raised when a requested service is not registered in the container."""


class CircularDependencyError(DIError):
    """Raised when a circular dependency chain is detected during resolution."""


class ResolutionError(DIError):
    """Raised when a service cannot be resolved due to invalid parameters or factories."""
