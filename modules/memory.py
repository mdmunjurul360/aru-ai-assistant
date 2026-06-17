"""SQLite-backed long-term memory for goals, projects, preferences, facts."""

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

logger = logging.getLogger("aru.memory")

CATEGORIES = ("goal", "project", "preference", "task", "fact", "note", "other")


@dataclass
class MemoryItem:
    id: int
    category: str
    title: str
    content: str
    tags: str
    created_at: str
    updated_at: str


class MemoryStore:
    """CRUD operations for Boss memories."""

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
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'other',
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_title ON memories(title)"
            )
        logger.info("Memory database ready at %s", self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            category=row["category"],
            title=row["title"],
            content=row["content"],
            tags=row["tags"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save(
        self,
        title: str,
        content: str,
        *,
        category: str = "other",
        tags: str = "",
    ) -> MemoryItem:
        category = category.lower() if category.lower() in CATEGORIES else "other"
        now = self._now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO memories (category, title, content, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (category, title.strip(), content.strip(), tags.strip(), now, now),
            )
            mem_id = cur.lastrowid
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
        assert row is not None
        logger.info("Memory saved: id=%s title=%s", mem_id, title)
        if self._activity:
            self._activity.log("memory", "save", f"id={mem_id} title={title[:60]}")
        return self._row_to_item(row)

    def search(self, query: str, *, limit: int = 10) -> list[MemoryItem]:
        q = f"%{query.strip()}%"
        if self._activity:
            self._activity.log("memory", "search", query[:100])
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memories
                WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? OR category LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (q, q, q, q, limit),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_by_id(self, mem_id: int) -> MemoryItem | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def list_all(self, *, category: str | None = None, limit: int = 20) -> list[MemoryItem]:
        with self._conn() as conn:
            if category:
                rows = conn.execute(
                    """
                    SELECT * FROM memories WHERE category = ?
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (category.lower(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def update(
        self,
        mem_id: int,
        *,
        title: str | None = None,
        content: str | None = None,
        category: str | None = None,
        tags: str | None = None,
    ) -> MemoryItem | None:
        existing = self.get_by_id(mem_id)
        if not existing:
            return None
        new_title = title.strip() if title else existing.title
        new_content = content.strip() if content else existing.content
        new_category = (
            category.lower()
            if category and category.lower() in CATEGORIES
            else existing.category
        )
        new_tags = tags.strip() if tags is not None else existing.tags
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE memories
                SET title = ?, content = ?, category = ?, tags = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_title, new_content, new_category, new_tags, now, mem_id),
            )
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
        assert row is not None
        logger.info("Memory updated: id=%s", mem_id)
        return self._row_to_item(row)

    def delete(self, mem_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Memory deleted: id=%s", mem_id)
            if self._activity:
                self._activity.log("memory", "delete", f"id={mem_id}")
        return deleted

    def context_for_ai(self, user_message: str, *, limit: int = 8) -> str:
        """Build a text block of relevant memories for the AI system prompt."""
        items = self.search(user_message, limit=limit)
        if not items:
            items = self.list_all(limit=5)
        if not items:
            return ""
        lines = []
        for m in items:
            lines.append(f"- [{m.category}] {m.title}: {m.content}")
        return "\n".join(lines)

    def format_item(self, item: MemoryItem) -> str:
        return (
            f"#{item.id} [{item.category}] {item.title}\n"
            f"{item.content}\n"
            f"Tags: {item.tags or '—'} | Updated: {item.updated_at[:10]}"
        )

    def format_list(self, items: list[MemoryItem]) -> str:
        if not items:
            return "কোনো মেমোরি পাওয়া যায়নি।"
        return "\n\n".join(self.format_item(i) for i in items)

    def remember(self, text: str, *, category: str = "fact") -> MemoryItem:
        """Quick-save a memory from free-form text."""
        stripped = text.strip()
        if "|" in stripped:
            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) >= 3:
                cat = parts[0].lower()
                title = parts[1]
                content = "|".join(parts[2:])
                return self.save(title, content, category=cat, tags=cat)
        if len(stripped) <= 60:
            return self.save(stripped, stripped, category=category, tags=category)
        title = stripped[:57] + "..."
        return self.save(title, stripped, category=category, tags=category)

    def handle_v2_command(self, text: str) -> str | None:
        """
        V2 memory commands:
        /remember <text>
        /memories [category]
        /forget <id>
        /searchmemory <query>
        """
        stripped = text.strip()
        lower = stripped.lower()

        if lower.startswith("/remember"):
            payload = stripped.split(maxsplit=1)[1] if " " in stripped else ""
            if not payload:
                return (
                    "ব্যবহার:\n"
                    "`/remember <তথ্য>`\n"
                    "`/remember category | title | content`"
                )
            item = self.remember(payload)
            return f"মনে রাখলাম ✅\n\n{self.format_item(item)}"

        if lower.startswith("/memories"):
            parts = stripped.split(maxsplit=1)
            cat = parts[1].strip().lower() if len(parts) > 1 else None
            if cat and cat not in CATEGORIES:
                return f"অবৈধ category। ব্যবহারযোগ্য: {', '.join(CATEGORIES)}"
            items = self.list_all(category=cat, limit=30)
            label = f" ({cat})" if cat else ""
            return f"🧠 মেমোরি{label} ({len(items)}):\n\n{self.format_list(items)}"

        if lower.startswith("/forget"):
            parts = stripped.split(maxsplit=1)
            if len(parts) < 2:
                return "ব্যবহার: `/forget <id>`"
            try:
                mem_id = int(parts[1].strip())
            except ValueError:
                return "অবৈধ memory ID।"
            if self.delete(mem_id):
                return f"মেমোরি #{mem_id} ভুলে গেছি।"
            return f"মেমোরি #{mem_id} পাওয়া যায়নি।"

        if lower.startswith("/searchmemory"):
            parts = stripped.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return "ব্যবহার: `/searchmemory <কীওয়ার্ড>`"
            query = parts[1].strip()
            items = self.search(query, limit=15)
            return f"🔎 মেমোরি খোঁজ ({len(items)}):\n\n{self.format_list(items)}"

        return None
