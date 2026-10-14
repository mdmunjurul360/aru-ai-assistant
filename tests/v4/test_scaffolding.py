"""Tests for Phase 1: Project Scaffolding & Packaging."""

from __future__ import annotations

import aru
import aru.core


def test_package_metadata() -> None:
    """Verify aru package exports correct version and metadata."""
    assert hasattr(aru, "__version__")
    assert aru.__version__.startswith("4.0.0")


def test_core_package_import() -> None:
    """Verify aru.core package is properly initialized."""
    assert aru.core is not None
