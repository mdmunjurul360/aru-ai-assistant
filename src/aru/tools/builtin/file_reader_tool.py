"""File Reader Tool with security sandbox for ARU AI V4."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from aru.tools.base import BaseTool
from aru.tools.models import ToolPermission, ToolResult


class FileReaderTool(BaseTool):
    """Tool for reading files and inspecting directories within safe project boundaries."""

    name = "file_reader"
    description = "Read text files, view directory contents, and inspect file metadata safely."
    required_permission = ToolPermission.READ
    timeout = 15.0

    SENSITIVE_PATTERNS = {".env", ".session", ".pem", ".key", "id_rsa"}

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "list", "info"],
                "description": "File operation to perform",
            },
            "path": {
                "type": "string",
                "description": "Relative path to target file or directory within workspace",
            },
            "offset": {
                "type": "integer",
                "description": "Starting line number for read (1-indexed)",
                "default": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
                "default": 100,
            },
        },
        "required": ["action", "path"],
    }

    def __init__(self, root_dir: Path | str | None = None) -> None:
        self._root = Path(root_dir).resolve() if root_dir else Path.cwd().resolve()

    def _resolve_safe_path(self, user_path: str) -> Path:
        """Resolve path and verify it does not escape the configured root."""
        clean = Path(user_path).as_posix().lstrip("/\\")
        target = (self._root / clean).resolve()

        # Check jail containment
        try:
            target.relative_to(self._root)
        except ValueError as err:
            raise PermissionError(f"Security violation: Access outside root directory is blocked: {user_path}") from err

        # Check sensitive file protection
        filename = target.name.lower()
        for pattern in self.SENSITIVE_PATTERNS:
            if pattern in filename or filename.startswith(pattern):
                raise PermissionError(f"Security violation: Access to sensitive file '{target.name}' is blocked.")

        return target

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()
        raw_path = kwargs.get("path", "").strip()

        if not raw_path:
            return ToolResult(success=False, error="Parameter 'path' is required.")

        try:
            safe_path = self._resolve_safe_path(raw_path)
        except PermissionError as p_err:
            return ToolResult(
                success=False,
                error=str(p_err),
                metadata={"security_blocked": True},
            )

        if action == "read":
            if not safe_path.exists():
                return ToolResult(success=False, error=f"File does not exist: {raw_path}")
            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path is not a regular file: {raw_path}")

            offset = max(1, int(kwargs.get("offset") or 1))
            limit = max(1, int(kwargs.get("limit") or 100))

            try:
                content = safe_path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                total_lines = len(lines)

                # 1-indexed slicing
                start_idx = offset - 1
                end_idx = start_idx + limit
                selected_lines = lines[start_idx:end_idx]

                output = "\n".join(selected_lines)
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"total_lines": total_lines, "offset": offset, "lines_returned": len(selected_lines)},
                )
            except Exception as err:
                return ToolResult(success=False, error=f"Failed to read file: {err}")

        elif action == "list":
            if not safe_path.exists():
                return ToolResult(success=False, error=f"Directory does not exist: {raw_path}")
            if not safe_path.is_dir():
                return ToolResult(success=False, error=f"Path is not a directory: {raw_path}")

            items: list[dict[str, Any]] = []
            try:
                for entry in sorted(safe_path.iterdir()):
                    name = entry.name
                    # Skip sensitive patterns from listing
                    if any(p in name.lower() for p in self.SENSITIVE_PATTERNS):
                        continue
                    items.append({
                        "name": name,
                        "is_dir": entry.is_dir(),
                        "size_bytes": entry.stat().st_size if entry.is_file() else 0,
                    })
                return ToolResult(success=True, output=items, metadata={"count": len(items)})
            except Exception as err:
                return ToolResult(success=False, error=f"Failed to list directory: {err}")

        elif action == "info":
            if not safe_path.exists():
                return ToolResult(success=False, error=f"Path does not exist: {raw_path}")

            stat = safe_path.stat()
            return ToolResult(
                success=True,
                output={
                    "path": raw_path,
                    "is_file": safe_path.is_file(),
                    "is_dir": safe_path.is_dir(),
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                },
            )

        return ToolResult(success=False, error=f"Unsupported file_reader action '{action}'.")
