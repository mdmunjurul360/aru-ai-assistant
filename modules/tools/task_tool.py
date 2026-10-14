"""Task Tool for Sprint 4 Integration Layer: wraps TaskManager."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from modules.tools.base import BaseTool, ToolPermission, ToolResult

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger
    from modules.tasks import TaskManager

logger = logging.getLogger("aru.tools.tasks")


class TaskTool(BaseTool):
    """
    Exposes smart task management as an MCP-compatible tool.
    Supports listing, creating, status updates, priority setting, and deleting tasks.
    """

    name = "tasks"
    description = (
        "Task management. List active tasks, create new tasks with priority, "
        "update progress status, set priorities, and complete or remove tasks."
    )
    required_permission = ToolPermission.READ
    timeout = 15.0

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "update_status", "set_priority", "delete"],
                "description": "Action: 'list' (view tasks), 'add' (create), 'update_status' (change status), 'set_priority' (change priority), 'delete' (remove).",
            },
            "id": {
                "type": "integer",
                "description": "Task ID (required for 'update_status', 'set_priority', 'delete').",
            },
            "title": {
                "type": "string",
                "description": "Task title (required for 'add').",
            },
            "description": {
                "type": "string",
                "description": "Optional task details or description.",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Priority level: low, medium, high, urgent.",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done", "cancelled"],
                "description": "Task status: pending, in_progress, done, cancelled.",
            },
            "due_date": {
                "type": "string",
                "description": "Optional due date formatted as YYYY-MM-DD or YYYY-MM-DD HH:MM.",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        task_manager: TaskManager | None = None,
        activity: ActivityLogger | None = None,
    ) -> None:
        self.tasks = task_manager
        self.activity = activity

    def _ensure_tasks(self) -> TaskManager:
        if self.tasks is None:
            from modules.activity_log import ActivityLogger
            from modules.tasks import TaskManager
            self.tasks = TaskManager(activity=self.activity or ActivityLogger())
        return self.tasks

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "list")
        mgr = self._ensure_tasks()

        # 1. List action
        if action == "list":
            status_filter = kwargs.get("status")
            priority_filter = kwargs.get("priority")
            items = mgr.list_tasks(status=status_filter, priority=priority_filter)
            formatted = mgr.format_task_list(items)
            output_list = [
                {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status,
                    "priority": t.priority,
                    "due_date": t.due_date,
                }
                for t in items
            ]
            return ToolResult(
                success=True,
                output=formatted,
                metadata={"count": len(items), "tasks": output_list},
            )

        # 2. Add action
        if action == "add":
            title = kwargs.get("title", "").strip()
            if not title:
                return ToolResult(
                    success=False,
                    error="Parameter 'title' is required for action 'add'.",
                )
            desc = kwargs.get("description", "").strip()
            priority = kwargs.get("priority", "medium")
            due_date = kwargs.get("due_date")
            try:
                task = mgr.add(
                    title=title,
                    description=desc,
                    priority=priority,
                    due_date=due_date,
                )
                return ToolResult(
                    success=True,
                    output=f"টাস্ক তৈরি হয়েছে ✅\n\n{mgr.format_task(task)}",
                    metadata={"task_id": task.id, "title": task.title},
                )
            except Exception as exc:
                return ToolResult(
                    success=False,
                    error=f"টাস্ক যোগ করতে ত্রুটি: {exc}",
                )

        # 3. Update status action
        if action == "update_status":
            task_id = kwargs.get("id")
            new_status = kwargs.get("status", "")
            if task_id is None or not new_status:
                return ToolResult(
                    success=False,
                    error="Parameters 'id' and 'status' are required for action 'update_status'.",
                )
            updated = mgr.set_status(int(task_id), new_status)
            if updated:
                return ToolResult(
                    success=True,
                    output=f"টাস্ক #{task_id} স্ট্যাটাস আপডেট: {new_status}\n\n{mgr.format_task(updated)}",
                    metadata={"task_id": updated.id, "status": updated.status},
                )
            return ToolResult(
                success=False,
                error=f"টাস্ক #{task_id} পাওয়া যায়নি বা অবৈধ স্ট্যাটাস।",
            )

        # 4. Set priority action
        if action == "set_priority":
            task_id = kwargs.get("id")
            new_priority = kwargs.get("priority", "")
            if task_id is None or not new_priority:
                return ToolResult(
                    success=False,
                    error="Parameters 'id' and 'priority' are required for action 'set_priority'.",
                )
            updated = mgr.set_priority(int(task_id), new_priority)
            if updated:
                return ToolResult(
                    success=True,
                    output=f"টাস্ক #{task_id} প্রায়োরিটি আপডেট: {new_priority}\n\n{mgr.format_task(updated)}",
                    metadata={"task_id": updated.id, "priority": updated.priority},
                )
            return ToolResult(
                success=False,
                error=f"টাস্ক #{task_id} পাওয়া যায়নি বা অবৈধ প্রায়োরিটি।",
            )

        # 5. Delete action
        if action == "delete":
            task_id = kwargs.get("id")
            if task_id is None:
                return ToolResult(
                    success=False,
                    error="Parameter 'id' is required for action 'delete'.",
                )
            deleted = mgr.delete(int(task_id))
            if deleted:
                return ToolResult(
                    success=True,
                    output=f"টাস্ক #{task_id} মুছে ফেলা হয়েছে।",
                    metadata={"deleted_id": task_id},
                )
            return ToolResult(
                success=False,
                error=f"টাস্ক #{task_id} পাওয়া যায়নি।",
            )

        return ToolResult(
            success=False,
            error=f"Unknown task action: '{action}'",
        )
