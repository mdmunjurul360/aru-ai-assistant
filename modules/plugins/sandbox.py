"""Sandbox enforcement environment for installable plugins."""

from __future__ import annotations

import logging
from typing import Any, Callable

from modules.plugins.manifest import PluginManifest, PluginPermission

logger = logging.getLogger("aru.plugins.sandbox")


class PluginSecurityError(PermissionError):
    """Raised when a plugin attempts an action exceeding its declared permissions."""
    pass


class PluginSandbox:
    """
    Guards plugin execution by enforcing declared permission boundaries.
    Validates filesystem, network, and administrative access requests.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        self.manifest = manifest
        self.allowed_permissions = set(manifest.permissions)

    def check_permission(self, permission: PluginPermission | str) -> None:
        perm = PluginPermission(permission.lower()) if isinstance(permission, str) else permission
        if perm not in self.allowed_permissions:
            raise PluginSecurityError(
                f"Plugin '{self.manifest.name}' attempted action requiring '{perm.value}' permission, "
                f"which is not declared in its manifest.json."
            )

    def run_guarded(self, action_name: str, required_permission: PluginPermission, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        self.check_permission(required_permission)
        logger.debug("Executing plugin action '%s' with verified permission '%s'", action_name, required_permission.value)
        return func(*args, **kwargs)
