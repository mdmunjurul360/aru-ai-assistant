"""Smart task manager with SQLite persistence (priority + status)."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator

from modules.config import DATABASE_DIR, DATABASE_PATH

if TYPE_CHECKING:
    from modules.activity_log import ActivityLogger

logger = logging.getLogger("aru.tasks")

STATUSES = ("pending", "in_progress", "done", "cancelled")
PRIORITIES = ("low", "medium", "high", "urgent")

PRIORITY_ICONS = {
    "low": "🔵",
    "medium": "🟡",
    "high": "🟠",
    "urgent": "🔴",
}

STATUS_ICONS = {
    "pending": "⏳",
    "in_progress": "🔄",
    "done": "✅",
    "cancelled": "❌",
}


@dataclass
class Task:
    id: int
    title: str
    description: str
    status: str
    priority: str
    created_at: str
    completed_at: str | None


class TaskManager:
    """Boss task CRUD with priority and status tracking."""

    def __init__(
        self,
        db_path: str | None = None,
        activity: "ActivityLogger | None" = None,
    ) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        self._activity = activity
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            self._migrate_schema(conn)
        logger.debug("Tasks table ready")

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Add v2 columns to existing v1 databases."""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "priority" not in cols:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium'"
            )
            logger.info("Tasks migrated: added priority column")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        priority = row["priority"] if "priority" in row.keys() else "medium"
        return Task(
            id=row["id"],
            title=row["title"],
            description=row["description"] or "",
            status=row["status"],
            priority=priority or "medium",
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def _log(self, action: str, detail: str) -> None:
        if self._activity:
            self._activity.log("tasks", action, detail)

    def add(
        self,
        title: str,
        description: str = "",
        *,
        priority: str = "medium",
    ) -> Task:
        priority = priority.lower() if priority.lower() in PRIORITIES else "medium"
        now = self._now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks (title, description, status, priority, created_at)
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (title.strip(), description.strip(), priority, now),
            )
            task_id = cur.lastrowid
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row is not None
        logger.info("Task added: id=%s title=%s priority=%s", task_id, title, priority)
        self._log("add", f"id={task_id} title={title[:60]} priority={priority}")
        return self._row_to_task(row)

    def list_tasks(
        self,
        *,
        include_done: bool = False,
        status: str | None = None,
    ) -> list[Task]:
        order = """
            CASE priority
                WHEN 'urgent' THEN 0
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                ELSE 3
            END,
            created_at DESC
        """
        with self._conn() as conn:
            if status and status in STATUSES:
                rows = conn.execute(
                    f"SELECT * FROM tasks WHERE status = ? ORDER BY {order}",
                    (status,),
                ).fetchall()
            elif include_done:
                rows = conn.execute(
                    f"SELECT * FROM tasks ORDER BY {order}"
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT * FROM tasks
                    WHERE status NOT IN ('done', 'cancelled')
                    ORDER BY {order}
                    """
                ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get(self, task_id: int) -> Task | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def set_status(self, task_id: int, status: str) -> Task | None:
        status = status.lower()
        if status not in STATUSES:
            return None
        task = self.get(task_id)
        if not task:
            return None
        now = self._now()
        completed_at = now if status == "done" else None
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?
                """,
                (status, completed_at, task_id),
            )
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row is not None
        logger.info("Task status: id=%s -> %s", task_id, status)
        self._log("status", f"id={task_id} status={status}")
        return self._row_to_task(row)

    def mark_done(self, task_id: int) -> Task | None:
        return self.set_status(task_id, "done")

    def set_priority(self, task_id: int, priority: str) -> Task | None:
        priority = priority.lower()
        if priority not in PRIORITIES:
            return None
        task = self.get(task_id)
        if not task:
            return None
        with self._conn() as conn:
            conn.execute(
                "UPDATE tasks SET priority = ? WHERE id = ?",
                (priority, task_id),
            )
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row is not None
        logger.info("Task priority: id=%s -> %s", task_id, priority)
        self._log("priority", f"id={task_id} priority={priority}")
        return self._row_to_task(row)

    def delete(self, task_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cur.rowcount:
            logger.info("Task deleted: id=%s", task_id)
            self._log("delete", f"id={task_id}")
        return cur.rowcount > 0

    def format_task(self, task: Task) -> str:
        status_icon = STATUS_ICONS.get(task.status, "•")
        priority_icon = PRIORITY_ICONS.get(task.priority, "")
        desc = f"\n   {task.description}" if task.description else ""
        return (
            f"{status_icon} {priority_icon} #{task.id} — {task.title}"
            f" [{task.status}/{task.priority}]{desc}"
        )

    def format_list(self, tasks: list[Task]) -> str:
        if not tasks:
            return "কোনো টাস্ক নেই। `/task add <কাজ>` দিয়ে নতুন টাস্ক যোগ করুন।"
        return "\n".join(self.format_task(t) for t in tasks)

    def pending_count(self) -> int:
        return len(self.list_tasks(include_done=False))

    def handle_command(self, text: str) -> str | None:
        """
        Parse /task commands. Returns response text or None if not a task command.
        """
        stripped = text.strip()
        if not stripped.lower().startswith("/task"):
            return None

        parts = stripped.split(maxsplit=2)
        if len(parts) < 2:
            return (
                "📋 **Smart Tasks (v2)**\n\n"
                "`/task add <title> [| description] [| priority]`\n"
                "`/task list` · `/task done <id>`\n"
                "`/task status <id> <pending|in_progress|done|cancelled>`\n"
                "`/task priority <id> <low|medium|high|urgent>`\n"
                "`/task delete <id>`"
            )

        sub = parts[1].lower()

        if sub == "add":
            if len(parts) < 3 or not parts[2].strip():
                return "ব্যবহার: `/task add <শিরোনাম> [| বিবরণ] [| priority]`"
            segments = [s.strip() for s in parts[2].split("|")]
            title = segments[0]
            description = segments[1] if len(segments) > 1 else ""
            priority = segments[2].lower() if len(segments) > 2 else "medium"
            task = self.add(title, description, priority=priority)
            return f"টাস্ক যোগ হয়েছে: {self.format_task(task)}"

        if sub == "list":
            tasks = self.list_tasks()
            header = f"📋 টাস্ক তালিকা ({len(tasks)} active)\n\n"
            return header + self.format_list(tasks)

        if sub in ("done", "complete"):
            if len(parts) < 3:
                return "ব্যবহার: `/task done <id>`"
            try:
                tid = int(parts[2])
            except ValueError:
                return "অবৈধ টাস্ক ID।"
            task = self.mark_done(tid)
            if not task:
                return f"টাস্ক #{tid} পাওয়া যায়নি।"
            return f"সম্পন্ন! {self.format_task(task)}"

        if sub == "status":
            if len(parts) < 3:
                return f"ব্যবহার: `/task status <id> <{'|'.join(STATUSES)}>`"
            status_parts = parts[2].split(maxsplit=1)
            if len(status_parts) < 2:
                return f"ব্যবহার: `/task status <id> <{'|'.join(STATUSES)}>`"
            try:
                tid = int(status_parts[0])
            except ValueError:
                return "অবৈধ টাস্ক ID।"
            new_status = status_parts[1].strip().lower()
            if new_status not in STATUSES:
                return f"অবৈধ status। ব্যবহারযোগ্য: {', '.join(STATUSES)}"
            task = self.set_status(tid, new_status)
            if not task:
                return f"টাস্ক #{tid} পাওয়া যায়নি।"
            return f"আপডেট হয়েছে: {self.format_task(task)}"

        if sub == "priority":
            if len(parts) < 3:
                return f"ব্যবহার: `/task priority <id> <{'|'.join(PRIORITIES)}>`"
            prio_parts = parts[2].split(maxsplit=1)
            if len(prio_parts) < 2:
                return f"ব্যবহার: `/task priority <id> <{'|'.join(PRIORITIES)}>`"
            try:
                tid = int(prio_parts[0])
            except ValueError:
                return "অবৈধ টাস্ক ID।"
            new_priority = prio_parts[1].strip().lower()
            if new_priority not in PRIORITIES:
                return f"অবৈধ priority। ব্যবহারযোগ্য: {', '.join(PRIORITIES)}"
            task = self.set_priority(tid, new_priority)
            if not task:
                return f"টাস্ক #{tid} পাওয়া যায়নি।"
            return f"প্রায়োরিটি আপডেট: {self.format_task(task)}"

        if sub == "delete":
            if len(parts) < 3:
                return "ব্যবহার: `/task delete <id>`"
            try:
                tid = int(parts[2])
            except ValueError:
                return "অবৈধ টাস্ক ID।"
            if self.delete(tid):
                return f"টাস্ক #{tid} মুছে ফেলা হয়েছে।"
            return f"টাস্ক #{tid} পাওয়া যায়নি।"

        return (
            "অজানা সাবকমান্ড।\n"
            "`add`, `list`, `done`, `status`, `priority`, `delete`"
        )
