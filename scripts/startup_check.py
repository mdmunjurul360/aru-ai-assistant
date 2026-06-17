#!/usr/bin/env python3
"""Non-interactive startup verification for Aru."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.config import (
    BOSS_TELEGRAM_ID,
    DATABASE_PATH,
    ENV_PATH,
    GROQ_MODEL,
    LOG_FILE,
    SECRET_CODE,
    SESSION_PATH,
    TG_API_HASH,
    TG_API_ID,
    env_file_status,
    reload_settings,
    validate_config,
)
from modules.activity_log import ActivityLogger
from modules.logging_setup import setup_logging
from modules.memory import MemoryStore
from modules.tasks import TaskManager
from modules.auth import verify_sender, unauthorized_message
from modules.ai import AruAI
from modules.research import ResearchAgent
from modules.voice import VoiceAssistant


async def main() -> int:
    reload_settings()
    logger = setup_logging()
    failures: list[str] = []
    print("=== Aru AI v2 Startup Check ===\n")

    # 1. Environment
    problems = validate_config()
    status = env_file_status()
    if problems:
        failures.extend([f"env: {p}" for p in problems])
        print(f"[FAIL] Environment:")
        for p in problems:
            print(f"       • {p}")
        empty = [k for k, v in status.items() if v == "empty" and not k.startswith("_")]
        if empty:
            print(f"       -> Save {ENV_PATH} (Ctrl+S) - keys exist but values are empty on disk.")
    else:
        print(f"[OK]   Environment: all required variables loaded")
        print(f"       BOSS_TELEGRAM_ID={BOSS_TELEGRAM_ID}, GROQ_MODEL={GROQ_MODEL}")

    # 2. Logging
    logger.info("Startup check: logging test")
    if LOG_FILE.exists():
        print(f"[OK]   Logging: {LOG_FILE} exists")
    else:
        print(f"[OK]   Logging: handler ready -> {LOG_FILE}")

    # 3. SQLite + v2 modules
    activity = ActivityLogger()
    mem = MemoryStore(activity=activity)
    tasks = TaskManager(activity=activity)
    mem.save("__startup__", "test", category="fact", tags="startup_check")
    found = mem.search("__startup__", limit=1)
    if found:
        mem.delete(found[0].id)

    v2_mem = mem.handle_v2_command("/remember v2 startup test")
    if v2_mem and "মনে রাখলাম" in v2_mem:
        items = mem.search("v2 startup", limit=1)
        if items:
            mem.delete(items[0].id)
        print("[OK]   Memory v2: /remember command works")
    else:
        failures.append("memory: v2 /remember failed")
        print("[FAIL] Memory v2 commands")

    task = tasks.add("v2 test", priority="high")
    tasks.set_status(task.id, "in_progress")
    tasks.delete(task.id)
    print("[OK]   Smart Tasks: priority + status work")

    activity.log("system", "startup_check", "v2 module test")
    print(f"[OK]   Activity log: {activity.count()} entries")

    if DATABASE_PATH.exists():
        print(f"[OK]   SQLite: {DATABASE_PATH} ({DATABASE_PATH.stat().st_size} bytes)")
    else:
        failures.append("sqlite: database file not created")
        print("[FAIL] SQLite: memory.db not found")

    # 4. Boss verification
    class FakeSender:
        def __init__(self, uid: int):
            self.id = uid

    if not BOSS_TELEGRAM_ID:
        failures.append("auth: BOSS_TELEGRAM_ID not set")
        print("[FAIL] Boss verification: BOSS_TELEGRAM_ID missing")
    else:
        ok_boss, _ = verify_sender(FakeSender(BOSS_TELEGRAM_ID))
        bad_boss, _ = verify_sender(FakeSender(999999999))
        if ok_boss and not bad_boss and unauthorized_message():
            print("[OK]   Boss verification: authorized / unauthorized paths work")
        else:
            failures.append("auth: boss verification logic failed")
            print("[FAIL] Boss verification")

    if SECRET_CODE:
        print("[OK]   SECRET_CODE configured")

    # 5. Groq + v2 AI modules
    ai = AruAI()
    if not ai.connect():
        failures.append("groq: client init failed")
        print("[FAIL] Groq: client init")
    else:
        reply = await ai.generate("Reply with exactly: OK", max_tokens=16)
        if reply and "ok" in reply.lower():
            print(f"[OK]   Groq: connected (model={GROQ_MODEL})")
        else:
            failures.append(f"groq: unexpected response: {reply[:80]!r}")
            print(f"[FAIL] Groq: bad response: {reply[:120]}")

        voice = VoiceAssistant(ai, activity=activity)
        if voice.connect():
            print("[OK]   Voice assistant: Groq Whisper client ready")
        else:
            print("[WARN] Voice assistant: Groq client init failed")

        research = ResearchAgent(ai, activity=activity)
        research_help = research.handle_command("/research")
        if research_help and "ব্যবহার" in research_help:
            print("[OK]   Research agent: command parser ready")
        else:
            failures.append("research: command parser failed")
            print("[FAIL] Research agent")

    # 6. Telegram session
    session_file = Path(str(SESSION_PATH) + ".session")
    if session_file.exists() and TG_API_ID and TG_API_HASH:
        from telethon import TelegramClient

        client = TelegramClient(str(SESSION_PATH), TG_API_ID, TG_API_HASH)
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                print(f"[OK]   Telegram: authorized as {me.username or me.first_name} (id={me.id})")
            else:
                failures.append("telegram: session exists but not authorized")
                print("[FAIL] Telegram: session file present but not logged in")
            await client.disconnect()
        except Exception as exc:
            failures.append(f"telegram: {exc}")
            print(f"[FAIL] Telegram: {exc}")
    elif not TG_API_ID or not TG_API_HASH:
        print("[SKIP] Telegram: configure TG_API_ID and TG_API_HASH in .env first")
    else:
        print(f"[WARN] Telegram: no session at {session_file}")
        print("       Run `python main.py` in terminal once to complete phone login.")

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All automated checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
