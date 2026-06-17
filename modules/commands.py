"""Slash-command handlers for memory and help."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from modules.memory import MemoryStore, CATEGORIES
from modules.scheduler import AruScheduler

logger = logging.getLogger("aru.commands")


def handle_memory_command(text: str, memory: MemoryStore) -> str | None:
    """
    /memory save <category> | <title> | <content>
    /memory search <query>
    /memory list [category]
    /memory update <id> | <title> | <content>
    /memory delete <id>
    """
    stripped = text.strip()
    if not stripped.lower().startswith("/memory"):
        return None

    parts = stripped.split(maxsplit=2)
    if len(parts) < 2:
        return _memory_help()

    sub = parts[1].lower()

    if sub == "save":
        if len(parts) < 3 or "|" not in parts[2]:
            return (
                "ব্যবহার:\n"
                "`/memory save <category> | <title> | <content>`\n"
                f"Categories: {', '.join(CATEGORIES)}"
            )
        segments = [s.strip() for s in parts[2].split("|")]
        if len(segments) < 3:
            return "তিনটি অংশ দিন: category | title | content"
        cat, title, content = segments[0], segments[1], "|".join(segments[2:])
        item = memory.save(title, content, category=cat, tags=cat)
        return f"মেমোরি সংরক্ষিত ✅\n\n{memory.format_item(item)}"

    if sub == "search":
        if len(parts) < 3:
            return "ব্যবহার: `/memory search <কীওয়ার্ড>`"
        items = memory.search(parts[2])
        return f"🔍 ফলাফল ({len(items)}):\n\n{memory.format_list(items)}"

    if sub == "list":
        cat = parts[2].strip().lower() if len(parts) > 2 else None
        items = memory.list_all(category=cat)
        return f"📚 মেমোরি ({len(items)}):\n\n{memory.format_list(items)}"

    if sub == "update":
        if len(parts) < 3 or "|" not in parts[2]:
            return "ব্যবহার: `/memory update <id> | <title> | <content>`"
        segments = [s.strip() for s in parts[2].split("|")]
        if len(segments) < 3:
            return "তিনটি অংশ: id | title | content"
        try:
            mem_id = int(segments[0])
        except ValueError:
            return "অবৈধ memory ID।"
        title = segments[1]
        content = "|".join(segments[2:])
        item = memory.update(mem_id, title=title, content=content)
        if not item:
            return f"মেমোরি #{mem_id} পাওয়া যায়নি।"
        return f"আপডেট হয়েছে ✅\n\n{memory.format_item(item)}"

    if sub == "delete":
        if len(parts) < 3:
            return "ব্যবহার: `/memory delete <id>`"
        try:
            mem_id = int(parts[2])
        except ValueError:
            return "অবৈধ memory ID।"
        if memory.delete(mem_id):
            return f"মেমোরি #{mem_id} মুছে ফেলা হয়েছে।"
        return f"মেমোরি #{mem_id} পাওয়া যায়নি।"

    return _memory_help()


def handle_reminder_command(text: str, scheduler: AruScheduler) -> str | None:
    parsed = scheduler.parse_reminder_command(text)
    if parsed is None and text.strip().lower().startswith("/remind"):
        return (
            "ব্যবহার:\n"
            "`/remind YYYY-MM-DD HH:MM your message`"
        )
    if parsed is None:
        return None
    run_at, message = parsed
    rid = f"reminder_{uuid.uuid4().hex[:8]}"
    if scheduler.schedule_reminder(rid, run_at, message):
        return f"রিমাইন্ডার সেট ✅\n{run_at.strftime('%Y-%m-%d %H:%M')}\n{message}"
    return "রিমাইন্ডার সেট করতে পারছি না।"


def handle_help_command(text: str) -> str | None:
    if text.strip().lower() not in ("/help", "/start", "/aru"):
        return None
    return (
        "🤖 **Aru AI v2 — Personal AI Assistant**\n\n"
        "**AI:** যেকোনো মেসেজ লিখুন, আমি উত্তর দেব।\n"
        "**Voice:** ভয়েস মেসেজ পাঠান — ট্রান্সক্রাইব করে উত্তর দেব।\n\n"
        "**Memory (v2):**\n"
        "`/remember <fact>` · `/memories` · `/forget <id>`\n"
        "`/searchmemory <q>`\n"
        "`/memory save cat | title | content` (v1 compatible)\n\n"
        "**Smart Tasks:**\n"
        "`/task add <title> [| desc] [| priority]`\n"
        "`/task list` · `/task status <id> <status>`\n"
        "`/task priority <id> <level>` · `/task done <id>`\n\n"
        "**Research:** `/research <topic>`\n\n"
        "**Scheduler:**\n"
        "`/remind YYYY-MM-DD HH:MM message`\n"
        "সকাল/রাতের অটো রিপোর্ট `.env` থেকে সেট করা।\n\n"
        "**Status:** `/status`"
    )


def handle_status_command(
    text: str,
    *,
    telegram_ok: bool,
    groq_ok: bool,
    memory_count: int,
    pending_tasks: int,
    voice_ok: bool = False,
    activity_count: int = 0,
) -> str | None:
    if text.strip().lower() != "/status":
        return None
    return (
        "📊 **Aru AI v2 Status**\n\n"
        f"Telegram: {'✅' if telegram_ok else '❌'}\n"
        f"Groq AI: {'✅' if groq_ok else '❌'}\n"
        f"Voice: {'✅' if voice_ok else '❌'}\n"
        f"Memories: {memory_count}\n"
        f"Pending tasks: {pending_tasks}\n"
        f"Activity logs: {activity_count}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


def _memory_help() -> str:
    return (
        "**Memory commands:**\n"
        "`/memory save category | title | content`\n"
        "`/memory search <query>`\n"
        "`/memory list [category]`\n"
        "`/memory update id | title | content`\n"
        "`/memory delete <id>`"
    )
