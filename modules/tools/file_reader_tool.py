"""File Reader Tool for Sprint 4 Integration Layer: sandboxed file inspection with security filters."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from modules.config import ROOT_DIR
from modules.tools.base import BaseTool, ToolPermission, ToolResult

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger

logger = logging.getLogger("aru.tools.file_reader")

FORBIDDEN_PATTERNS = {
    ".env",
    ".env.example",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".key",
    ".session",
    ".session-journal",
}


class FileReaderTool(BaseTool):
    """
    Sandboxed file reading and exploration tool.
    Strictly prevents directory traversal and protects sensitive credentials and tokens.
    """

    name = "file_reader"
    description = (
        "Safely inspect and read workspace files. Supports line offsets, limits, "
        "and sandboxed directory inspection while strictly protecting secrets."
    )
    required_permission = ToolPermission.READ
    timeout = 15.0

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "info", "list"],
                "description": "File operation: 'read' (read contents), 'info' (metadata), 'list' (directory files).",
            },
            "path": {
                "type": "string",
                "description": "Relative or absolute file path within the project workspace.",
            },
            "offset": {
                "type": "integer",
                "description": "Starting line number (1-indexed) for read action. Defaults to 1.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read (max 500). Defaults to 100.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum total characters to return. Defaults to 8000.",
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        root_dir: Path | str | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        self.root_dir = Path(root_dir or ROOT_DIR).resolve()
        self.activity = activity

    def _sanitize_path(self, raw_path: str) -> tuple[Path | None, str | None]:
        """Verify path is contained within self.root_dir and not a sensitive secret."""
        try:
            target = (self.root_dir / raw_path).resolve()
        except Exception as exc:
            return None, f"Invalid path format: {exc}"

        # 1. Sandbox check (path traversal prevention)
        try:
            target.relative_to(self.root_dir)
        except ValueError:
            return None, "Security violation: Access outside the workspace root is forbidden."

        # 2. Sensitive file filters
        name_lower = target.name.lower()
        if any(name_lower == pattern or name_lower.endswith(pattern) for pattern in FORBIDDEN_PATTERNS):
            return None, f"Security violation: Access to sensitive file '{target.name}' is blocked."

        if any(part.startswith(".git") for part in target.parts):
            return None, "Security violation: Access to internal version control files is forbidden."

        return target, None

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "read")
        raw_path = kwargs.get("path", "")
        offset = int(kwargs.get("offset", 1))
        limit = min(int(kwargs.get("limit", 100)), 500)
        max_chars = min(int(kwargs.get("max_chars", 8000)), 32000)

        target, error = self._sanitize_path(raw_path)
        if error:
            logger.warning("FileReader security rejection: path=%s error=%s", raw_path, error)
            return ToolResult(
                success=False,
                error=error,
                metadata={"path": raw_path, "security_blocked": True},
            )

        if not target.exists():
            return ToolResult(
                success=False,
                error=f"Path '{target.relative_to(self.root_dir)}' does not exist.",
                metadata={"path": str(target)},
            )

        # Handle 'info'
        if action == "info":
            stat = target.stat()
            rel_path = str(target.relative_to(self.root_dir))
            info = {
                "path": rel_path,
                "is_dir": target.is_dir(),
                "is_file": target.is_file(),
                "size_bytes": stat.st_size if target.is_file() else None,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
            return ToolResult(success=True, output=info, metadata={"path": rel_path})

        # Handle 'list'
        if action == "list":
            if not target.is_dir():
                return ToolResult(
                    success=False,
                    error=f"Cannot list: '{target.relative_to(self.root_dir)}' is not a directory.",
                )
            items = []
            for child in sorted(target.iterdir()):
                name = child.name
                if name.startswith(".") or any(name.lower().endswith(p) for p in FORBIDDEN_PATTERNS):
                    continue
                items.append({
                    "name": name,
                    "is_dir": child.is_dir(),
                    "size_bytes": child.stat().st_size if child.is_file() else 0,
                })
            return ToolResult(
                success=True,
                output=items,
                metadata={"path": str(target.relative_to(self.root_dir)), "count": len(items)},
            )

        # Handle 'read'
        if not target.is_file():
            return ToolResult(
                success=False,
                error=f"Cannot read: '{target.relative_to(self.root_dir)}' is a directory, not a file.",
            )

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            total_lines = len(lines)

            start_idx = max(0, offset - 1)
            end_idx = min(total_lines, start_idx + limit)
            selected_lines = lines[start_idx:end_idx]

            numbered_lines = [
                f"{i + 1:4d} | {line}"
                for i, line in enumerate(selected_lines, start=start_idx)
            ]
            result_text = "\n".join(numbered_lines)

            if len(result_text) > max_chars:
                result_text = result_text[:max_chars] + "\n... [truncated]"

            rel_path = str(target.relative_to(self.root_dir))
            return ToolResult(
                success=True,
                output=result_text,
                metadata={
                    "path": rel_path,
                    "total_lines": total_lines,
                    "start_line": start_idx + 1,
                    "end_line": end_idx,
                    "returned_lines": len(selected_lines),
                },
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to read file: {exc}",
                metadata={"path": raw_path},
            )
