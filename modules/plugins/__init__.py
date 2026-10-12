"""Plugin System package: manifest, permissions, sandbox, auto-discovery and loading."""

from __future__ import annotations

from modules.plugins.loader import LoadedPlugin, PluginLoader
from modules.plugins.manifest import PluginManifest, PluginPermission
from modules.plugins.sandbox import PluginSandbox, PluginSecurityError

__all__ = [
    "PluginPermission",
    "PluginManifest",
    "PluginSandbox",
    "PluginSecurityError",
    "PluginLoader",
    "LoadedPlugin",
]
