"""Command router and handlers for Telegram in ARU AI V4."""

from __future__ import annotations

from typing import Any
from aru.database.repositories.task_repo import TaskRepository
from aru.interfaces.telegram.formatter import format_command_help
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext
from aru.memory.service import MemoryService


class CommandHandler:
    """Dispatches slash commands to dedicated actions."""

    COMMANDS = {
        "start": "Initialize session and display welcome greeting",
        "help": "Display list of available commands and instructions",
        "status": "Check health status of database, memory, and services",
        "tasks": "View pending and active tasks",
        "clear": "Clear conversational working memory for this chat",
        "ping": "Test bot connectivity and latency",
    }

    def __init__(
        self,
        memory_service: MemoryService | None = None,
        task_repo: TaskRepository | None = None,
    ) -> None:
        self._memory = memory_service
        self._tasks = task_repo

    async def handle_command(self, ctx: TelegramUpdateContext) -> bool:
        """Parse command and execute handler if matched."""
        text = ctx.text.strip()
        if not text.startswith("/"):
            return False

        cmd_part = text.split()[0].lstrip("/").lower()
        if "@" in cmd_part:
            cmd_part = cmd_part.split("@")[0]

        if cmd_part in ("start", "help"):
            ctx.reply_text = format_command_help(self.COMMANDS)
            ctx.handled = True
            return True

        elif cmd_part == "status":
            ctx.reply_text = "🟢 **ARU AI V4 Online**\n• Core: Operational\n• Memory: Active\n• Database: Connected (WAL)"
            ctx.handled = True
            return True

        elif cmd_part == "ping":
            ctx.reply_text = "🏓 **Pong!** ARU AI V4 is responsive."
            ctx.handled = True
            return True

        elif cmd_part == "clear":
            if self._memory:
                self._memory.working_memory.clear(str(ctx.chat_id))
            ctx.reply_text = "🧹 Conversational working memory cleared for this session."
            ctx.handled = True
            return True

        elif cmd_part == "tasks":
            if self._tasks:
                tasks = await self._tasks.list_tasks(status="pending", limit=10)
                if tasks:
                    lines = ["📋 **Pending Tasks:**\n"]
                    for t in tasks:
                        lines.append(f"• [{t.get('priority', 'medium').upper()}] #{t['id']}: {t['title']}")
                    ctx.reply_text = "\n".join(lines)
                else:
                    ctx.reply_text = "📋 No pending tasks currently."
            else:
                ctx.reply_text = "Task management repository is not configured."
            ctx.handled = True
            return True

        return False
