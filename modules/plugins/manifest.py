"""Plugin manifest parsing and permission specification."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PluginPermission(str, Enum):
    """Granular permissions granted to installable plugins."""
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    SHELL = "shell"
    ADMIN = "admin"


@dataclass
class PluginManifest:
    """Plugin manifest.json schema."""
    name: str
    version: str
    description: str
    author: str
    entrypoint: str  # e.g. "plugin.py"
    permissions: list[PluginPermission] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginManifest:
        perms = [
            PluginPermission(p.lower()) if isinstance(p, str) else p
            for p in data.get("permissions", [])
        ]
        return cls(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", "Unknown"),
            entrypoint=data.get("entrypoint", "plugin.py"),
            permissions=perms,
            tools=data.get("tools", []),
            config_schema=data.get("config_schema", {}),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> PluginManifest:
        p = Path(path)
        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
        return cls.from_dict(data)
