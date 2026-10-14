"""Task repository for ARU AI V4."""

from __future__ import annotations

from typing import Any
from aru.database.repositories.base import BaseRepository


class TaskRepository(BaseRepository[dict[str, Any]]):
    """Manages persistent tasks, priorities, statuses, and due dates."""

    async def create(
        self,
        title: str,
        description: str = "",
        status: str = "pending",
        priority: str = "medium",
        due_date: str | None = None,
    ) -> int:
        """Create a new task and return its generated ID."""
        return await self._execute_insert(
            """
            INSERT INTO tasks (title, description, status, priority, due_date)
            VALUES (?, ?, ?, ?, ?);
            """,
            (title, description, status, priority, due_date),
        )

    async def get_by_id(self, task_id: int) -> dict[str, Any] | None:
        """Retrieve task by numeric primary key."""
        return await self._fetch_one("SELECT * FROM tasks WHERE id = ?;", (task_id,))

    async def list_tasks(
        self,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tasks optionally filtered by status and priority."""
        conditions: list[str] = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if priority:
            conditions.append("priority = ?")
            params.append(priority)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM tasks {where_clause} ORDER BY id DESC LIMIT ?;"
        params.append(limit)

        return await self._fetch_all(query, tuple(params))

    async def update_status(self, task_id: int, status: str) -> bool:
        """Update status of a task."""
        count = await self._execute_mutation(
            "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (status, task_id),
        )
        return count > 0

    async def update_priority(self, task_id: int, priority: str) -> bool:
        """Update priority of a task."""
        count = await self._execute_mutation(
            "UPDATE tasks SET priority = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (priority, task_id),
        )
        return count > 0

    async def delete(self, task_id: int) -> bool:
        """Delete a task."""
        count = await self._execute_mutation("DELETE FROM tasks WHERE id = ?;", (task_id,))
        return count > 0

    async def count(self, status: str | None = None) -> int:
        """Count tasks, optionally filtered by status."""
        if status:
            row = await self._fetch_one(
                "SELECT COUNT(*) as cnt FROM tasks WHERE status = ?;",
                (status,),
            )
        else:
            row = await self._fetch_one("SELECT COUNT(*) as cnt FROM tasks;")
        return row["cnt"] if row else 0
