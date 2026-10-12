"""PluginLoader: Auto-discovery, verification, and registration of plugins."""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modules.config import ROOT_DIR
from modules.plugins.manifest import PluginManifest
from modules.plugins.sandbox import PluginSandbox
from modules.tools.base import BaseTool
from modules.tools.manager import ToolManager

logger = logging.getLogger("aru.plugins.loader")


@dataclass
class LoadedPlugin:
    """Active loaded plugin instance."""
    manifest: PluginManifest
    sandbox: PluginSandbox
    plugin_dir: Path
    module: Any
    registered_tools: list[str]


class PluginLoader:
    """
    Scans the plugins/ directory, validates manifest.json files,
    enforces permission sandboxing, and registers discovered tools.
    """

    def __init__(
        self,
        plugins_dir: str | Path | None = None,
        tool_manager: ToolManager | None = None,
    ) -> None:
        self.plugins_dir = Path(plugins_dir or (ROOT_DIR / "plugins"))
        self.tool_manager = tool_manager
        self._loaded_plugins: dict[str, LoadedPlugin] = {}

    def discover_and_load_all(self) -> list[LoadedPlugin]:
        """Scan plugins directory for valid plugins."""
        if not self.plugins_dir.exists():
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            return []

        loaded: list[LoadedPlugin] = []
        for plugin_folder in self.plugins_dir.iterdir():
            if plugin_folder.is_dir():
                manifest_path = plugin_folder / "manifest.json"
                if manifest_path.exists():
                    try:
                        p = self.load_plugin(plugin_folder)
                        if p:
                            loaded.append(p)
                    except Exception as exc:
                        logger.error("Failed loading plugin from %s: %s", plugin_folder.name, exc)

        return loaded

    def load_plugin(self, plugin_folder: Path) -> LoadedPlugin | None:
        manifest_file = plugin_folder / "manifest.json"
        manifest = PluginManifest.from_file(manifest_file)
        sandbox = PluginSandbox(manifest)

        entry_path = plugin_folder / manifest.entrypoint
        if not entry_path.exists():
            logger.warning("Plugin '%s' entrypoint '%s' not found", manifest.name, manifest.entrypoint)
            return None

        # Dynamically load Python module
        spec = importlib.util.spec_from_file_location(f"aru_plugin_{manifest.name}", entry_path)
        if not spec or not spec.loader:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Look for register_tools or get_tools hook
        registered_tools: list[str] = []
        if hasattr(module, "register_tools") and self.tool_manager:
            tools = module.register_tools(sandbox)
            if isinstance(tools, list):
                for t in tools:
                    if isinstance(t, BaseTool):
                        self.tool_manager.register_tool(t)
                        registered_tools.append(t.name)

        loaded = LoadedPlugin(
            manifest=manifest,
            sandbox=sandbox,
            plugin_dir=plugin_folder,
            module=module,
            registered_tools=registered_tools,
        )
        self._loaded_plugins[manifest.name] = loaded
        logger.info("Plugin '%s' v%s loaded with %d tools", manifest.name, manifest.version, len(registered_tools))
        return loaded

    def get_plugin(self, name: str) -> LoadedPlugin | None:
        return self._loaded_plugins.get(name)

    def list_loaded(self) -> list[dict[str, Any]]:
        return [
            {
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "author": p.manifest.author,
                "permissions": [perm.value for perm in p.manifest.permissions],
                "tools": p.registered_tools,
            }
            for p in self._loaded_plugins.values()
        ]
