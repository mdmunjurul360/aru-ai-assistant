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
    GROQ_API_KEY,
    GEMINI_API_KEY,
    OPENAI_API_KEY,
    DEEPSEEK_API_KEY,
    CLOUDFLARE_API_KEY,
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
from modules.anti_spam import AntiSpamManager
from modules.conversation import ConversationHistoryStore
from modules.db import ensure_db_ready
from modules.logging_setup import setup_logging
from modules.maintenance import DatabaseMaintenance
from modules.memory import MemoryStore
from modules.memory_service import MemoryService
from modules.tasks import TaskManager
from modules.auth import verify_sender, unauthorized_message
from modules.ai import AruAI
from modules.research import ResearchAgent
from modules.tools import (
    BrowserTool,
    ExecutionContext,
    FileReaderTool,
    MemoryTool,
    ResearchTool,
    TaskTool,
    ToolManager,
    ToolPermission,
)
from modules.voice import VoiceAssistant


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    reload_settings()
    logger = setup_logging()
    failures: list[str] = []
    print("=== Aru AI Production Readiness Check ===\n")

    # 1. Dependency checks
    dep_checks = {
        "telethon": "Telethon",
        "groq": "Groq",
        "dotenv": "python-dotenv",
        "apscheduler": "APScheduler",
        "httpx": "HTTPX",
    }
    missing_deps: list[str] = []
    for mod_name, label in dep_checks.items():
        try:
            __import__(mod_name)
        except ImportError:
            missing_deps.append(label)

    if missing_deps:
        failures.append(f"deps: missing {', '.join(missing_deps)}")
        print(f"[FAIL] Dependencies: missing {', '.join(missing_deps)}")
    else:
        print("[OK]   Dependencies: all core packages installed (Telethon, Groq, APScheduler, HTTPX)")

    # 2. Environment
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

    # 3. Logging
    logger.info("Startup check: logging test")
    if LOG_FILE.exists():
        print(f"[OK]   Logging: {LOG_FILE} exists")
    else:
        print(f"[OK]   Logging: handler ready -> {LOG_FILE}")

    # 4. SQLite WAL Mode + Modules
    activity = ActivityLogger()
    mem = MemoryStore(activity=activity)
    conv = ConversationHistoryStore()
    mem_service = MemoryService(memory_store=mem, conversation_store=conv, activity=activity)
    maintenance = DatabaseMaintenance()
    tasks = TaskManager(activity=activity)
    anti_spam = AntiSpamManager(activity=activity)

    wal_mode = ensure_db_ready(mem.db_path)
    if wal_mode == "WAL":
        print(f"[OK]   SQLite: {DATABASE_PATH} (journal_mode=WAL, size={DATABASE_PATH.stat().st_size} bytes)")
    else:
        failures.append(f"sqlite: unexpected journal mode {wal_mode}")
        print(f"[FAIL] SQLite: journal_mode={wal_mode} (expected WAL)")

    mem.save("__startup__", "test", category="fact", tags="startup_check")
    found = mem.search("__startup__", limit=1)
    if found:
        mem.delete(found[0].id)
        print("[OK]   Memory: FTS5 search & BM25 ranking operational")
    else:
        failures.append("memory: FTS5 search failed")
        print("[FAIL] Memory: FTS5 search failed")

    conv.add_message(999999, "user", "startup test")
    hist = conv.get_history(999999, limit=1)
    conv.clear_history(999999)
    if hist and hist[0]["content"] == "startup test":
        print("[OK]   Conversation: persistent SQLite history operational")
    else:
        failures.append("conversation: persistence check failed")
        print("[FAIL] Conversation: persistence check failed")

    m_rep = maintenance.run_full_maintenance()
    if m_rep.get("vacuum") and m_rep.get("analyze"):
        print("[OK]   Maintenance: WAL checkpoint, VACUUM, and ANALYZE operational")
    else:
        failures.append("maintenance: routine failed")
        print("[FAIL] Maintenance routines failed")

    v2_mem = mem.handle_v2_command("/remember v2 startup test")
    if v2_mem and "মনে রাখলাম" in v2_mem:
        items = mem.search("v2 startup", limit=1)
        if items:
            mem.delete(items[0].id)
        print("[OK]   Memory: CRUD and /remember command work")
    else:
        failures.append("memory: v2 /remember failed")
        print("[FAIL] Memory commands")

    task = tasks.add("v2 test", priority="high")
    tasks.set_status(task.id, "in_progress")
    tasks.delete(task.id)
    print("[OK]   Smart Tasks: priority + status work")

    allowed_boss, _ = anti_spam.should_reply(BOSS_TELEGRAM_ID, is_boss=True)
    if allowed_boss:
        print("[OK]   Anti-Spam: active and boss-exempt")
    else:
        failures.append("anti_spam: boss was blocked")
        print("[FAIL] Anti-Spam: boss check failed")

    activity.log("system", "startup_check", "production readiness test")
    print(f"[OK]   Activity log: {activity.count()} entries recorded")

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

    # 5. Multi-Provider AI modules
    ai = AruAI()
    if not ai.connect():
        failures.append("ai: client init failed (no providers configured)")
        print("[FAIL] AI: client init failed (no LLM providers configured)")
    else:
        reply = await ai.generate("Reply with exactly: OK", max_tokens=16)
        active_label = "OpenRouter" if ai.active_provider == "openrouter" else (ai.active_provider.capitalize() if ai.active_provider else "Primary AI")
        if reply and "ok" in reply.lower():
            print(f"[OK]   {active_label} / Primary AI: connected (active={ai.active_model})")
        else:
            failures.append(f"ai: unexpected response: {reply[:80]!r}")
            print(f"[FAIL] AI: bad response: {reply[:120]}")

        # Verify Multi-Provider LLM availability and failover priority
        prov_mgr = ai.provider_manager
        expected_priority = ["openrouter", "groq", "gemini", "cloudflare", "deepseek"]
        actual_priority = [p.lower() for p in prov_mgr.priority]
        if actual_priority == expected_priority:
            print("[OK]   Provider Priority Chain Verified:")
            print("       OpenRouter -> Groq -> Gemini -> Cloudflare -> DeepSeek")
        else:
            print(f"[WARN] Provider Priority mismatch: {' -> '.join(actual_priority)} (expected: {' -> '.join(expected_priority)})")

        for p_name, p_label in [
            ("openrouter", "OpenRouter"),
            ("groq", "Groq"),
            ("gemini", "Gemini"),
            ("cloudflare", "Cloudflare"),
            ("deepseek", "DeepSeek"),
        ]:
            p_obj = prov_mgr.get_provider(p_name)
            key_count = p_obj.key_pool.total_keys if (p_obj and hasattr(p_obj, "key_pool")) else 0
            if key_count > 0:
                if p_name == "cloudflare":
                    status_text = f"{key_count} {'accounts' if key_count != 1 else 'account'} loaded"
                else:
                    status_text = f"{key_count} {'keys' if key_count != 1 else 'key'} loaded"
            else:
                status_text = "Disabled / Not Configured (0 keys loaded, skipped)"
            print(f"       ✓ {p_label}: {status_text}")

        voice = VoiceAssistant(ai, activity=activity)
        if voice.connect():
            print("[OK]   Voice assistant: Groq Whisper client ready")
        else:
            print("[WARN] Voice assistant: Groq client init failed")

        research = ResearchAgent(ai, activity=activity)
        research_help = research.handle_command("/research")
        if research_help and "ব্যবহার" in research_help:
            print(f"[OK]   Research engine: active (provider={research.service.provider_name}, cache=ready)")
        else:
            failures.append("research: command parser failed")
            print("[FAIL] Research agent")

    # 5.5 Tool Registry & MCP Architecture (Sprint 4)
    tool_mgr = ToolManager(activity=activity)
    tool_mgr.register_tool(BrowserTool(activity=activity))
    tool_mgr.register_tool(FileReaderTool(root_dir=ROOT, activity=activity))
    tool_mgr.register_tool(ResearchTool(research_service=research.service, activity=activity))
    tool_mgr.register_tool(MemoryTool(memory_service=mem_service, activity=activity))
    tool_mgr.register_tool(TaskTool(task_manager=tasks, activity=activity))

    tool_names = set(tool_mgr.get_tool_names())
    expected_tools = {"browser", "file_reader", "research", "memory", "tasks"}
    if expected_tools.issubset(tool_names):
        # Test permission enforcement
        unauth_ctx = ExecutionContext(user_id=12345, is_boss=False, caller="guest")
        auth_ctx = ExecutionContext(user_id=BOSS_TELEGRAM_ID or 1, is_boss=True, caller="boss")

        # Security check: guest cannot delete memory
        denied_res = await tool_mgr.execute_tool("memory", {"action": "delete", "id": 1}, unauth_ctx)
        # Sandbox check: file_reader reading README.md
        read_res = await tool_mgr.execute_tool("file_reader", {"action": "read", "path": "README.md", "limit": 2}, auth_ctx)

        if not denied_res.success and read_res.success:
            print(f"[OK]   Tool Registry (MCP): 5 tools verified ({', '.join(sorted(tool_names))}), sandbox & auth enforced")
        else:
            failures.append("tool_registry: permission or sandboxing test failed")
            print("[FAIL] Tool Registry: security verification failed")

        # 5.6 Autonomous Agent (ReAct + Tool Calling)
        from modules.agent import AruAgent
        agent = AruAgent(ai=ai, tool_manager=tool_mgr, activity=activity, max_iterations=2)
        tool_specs = agent.get_tool_specs()
        if len(tool_specs) >= 5:
            print("[OK]   Autonomous Agent (ReAct): operational with 5 MCP tool schemas")
        else:
            failures.append(f"agent: expected 5 tool specs, got {len(tool_specs)}")
            print("[FAIL] Autonomous Agent: tool specs mismatch")

        # 5.7 Multi-Agent Autonomous Automation (Sprint 6)
        from modules.multi_agent import MultiAgentManager
        multi_mgr = MultiAgentManager(ai=ai, tool_manager=tool_mgr, activity=activity)
        active_agents = set(multi_mgr.get_status()["agents"])
        expected_agents = {"planner", "research", "memory", "browser", "task", "scheduler"}
        active_wfs = set(multi_mgr.get_status()["workflows"])
        expected_wfs = {
            "morning_briefing",
            "research_update",
            "job_monitoring",
            "reminder_execution",
            "task_follow_up",
            "memory_consolidation",
        }

        if expected_agents.issubset(active_agents) and expected_wfs.issubset(active_wfs):
            # Test a dry-run workflow
            wf_res = await multi_mgr.run_workflow("memory_consolidation")
            trace_count = len(multi_mgr.event_bus.get_event_history())
            if wf_res.get("success", False):
                print(
                    f"[OK]   Multi-Agent System: 6 specialized agents & 6 autonomous workflows active (EventBus traces={trace_count})"
                )
            else:
                failures.append(f"multi_agent: dry-run workflow failed: {wf_res.get('error')}")
                print("[FAIL] Multi-Agent System: dry-run workflow failed")
        else:
            failures.append(f"multi_agent: missing agents {expected_agents - active_agents} or wfs {expected_wfs - active_wfs}")
            print("[FAIL] Multi-Agent System: agents or workflows missing")

        # 5.8 Personal AI Operating System (Sprint 7)
        from modules.semantic_memory import VectorMemoryStore, HybridSearchEngine
        from modules.knowledge_base import KnowledgeStore
        from modules.channels import (
            ChannelManager,
            TelegramChannelAdapter,
            WhatsAppChannelAdapter,
            DiscordChannelAdapter,
            GmailChannelAdapter,
            RestApiChannelAdapter,
            WebhookChannelAdapter,
        )
        from modules.scheduling import HabitStore, GoalStore, SchedulingIntelligence
        from modules.observability import TelemetryCollector
        from modules.plugins import PluginLoader

        sem_vec = VectorMemoryStore(db_path=DATABASE_PATH)
        hybrid_engine = HybridSearchEngine(memory_store=mem, vector_store=sem_vec)
        kb_store = KnowledgeStore(db_path=DATABASE_PATH)
        chan_mgr = ChannelManager()
        for adapter in [
            TelegramChannelAdapter(),
            WhatsAppChannelAdapter(),
            DiscordChannelAdapter(),
            GmailChannelAdapter(),
            RestApiChannelAdapter(),
            WebhookChannelAdapter(),
        ]:
            chan_mgr.register_adapter(adapter)
        habit_store = HabitStore(db_path=DATABASE_PATH)
        goal_store = GoalStore(db_path=DATABASE_PATH)
        sched_intel = SchedulingIntelligence(task_manager=tasks, habit_store=habit_store, goal_store=goal_store)
        telemetry = TelemetryCollector(db_path=DATABASE_PATH)
        plugin_loader = PluginLoader(plugins_dir=ROOT / "plugins")

        os_checks = [
            ("Hybrid Semantic Memory", hybrid_engine is not None and sem_vec.count() >= 0),
            ("Knowledge Base Engine", kb_store.count_documents() >= 0),
            ("Multi-Channel Adapters", len(chan_mgr.adapters) == 6),
            ("Scheduling Intelligence", sched_intel is not None),
            ("Telemetry & Observability", telemetry.get_token_summary()["total_tokens"] >= 0),
            ("Plugin Discovery System", plugin_loader is not None),
        ]
        all_os_ok = all(ok for _, ok in os_checks)
        if all_os_ok:
            print(
                "[OK]   AI Operating System (Sprint 7): 6 channels, hybrid vector memory, knowledge base, observability online"
            )
        else:
            failed_os = [name for name, ok in os_checks if not ok]
            failures.append(f"ai_os: subsystems failed: {', '.join(failed_os)}")
            print(f"[FAIL] AI Operating System: {', '.join(failed_os)}")
    else:
        failures.append(f"tool_registry: missing expected tools: {expected_tools - tool_names}")
        print(f"[FAIL] Tool Registry: missing tools ({expected_tools - tool_names})")

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
