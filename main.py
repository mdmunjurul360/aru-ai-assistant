#!/usr/bin/env python3
"""
Aru AI v2 — Personal Telegram UserBot AI Assistant
Run: python main.py
"""

from __future__ import annotations

import mimetypes
mimetypes.init()
mimetypes._db = mimetypes.MimeTypes()

import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    RPCError,
    SessionPasswordNeededError,
)

from modules.activity_log import ActivityLogger
from modules.agent import AruAgent
from modules.ai import AruAI
from modules.anti_spam import AntiSpamManager
from modules.auth import unauthorized_message, verify_sender, verify_secret_code
from modules.browser import BrowserAutomation
from modules.commands import (
    handle_agent_command,
    handle_cooldown_command,
    handle_help_command,
    handle_memory_command,
    handle_plan_command,
    handle_reminder_command,
    handle_status_command,
    handle_tools_command,
    handle_workflow_command,
)
from modules.config import (
    AGENT_MAX_ITERATIONS,
    BOSS_TELEGRAM_ID,
    CONVERSATION_HISTORY_LIMIT,
    DATABASE_DIR,
    ENV_PATH,
    LOGS_DIR,
    ROOT_DIR,
    SESSION_PATH,
    SESSIONS_DIR,
    TG_API_HASH,
    TG_API_ID,
    env_file_status,
    reload_settings,
    validate_config,
)
from modules.conversation import ConversationHistoryStore
from modules.db import ensure_db_ready
from modules.logging_setup import setup_logging
from modules.memory import MemoryStore
from modules.memory_service import MemoryService
from modules.multi_agent import MultiAgentManager
from modules.research import ResearchAgent
from modules.scheduler import AruScheduler
from modules.tasks import TaskManager
from modules.tools import (
    BrowserTool,
    ExecutionContext,
    FileReaderTool,
    MemoryTool,
    ResearchTool,
    TaskTool,
    ToolManager,
)
from modules.pdf_processor import PDFProcessor
from modules.vision.image_handler import is_image_message, process_image_message
from modules.voice import VoiceAssistant

logger = setup_logging()


def is_pdf_message(message: Any) -> bool:
    """Detect if Telegram message carries a PDF document."""
    if not message:
        return False
    f = getattr(message, "file", None)
    if f and getattr(f, "ext", None) and (f.ext or "").lower() == ".pdf":
        return True
    doc = getattr(message, "document", None)
    if doc:
        mime = (getattr(doc, "mime_type", "") or "").lower()
        if mime == "application/pdf":
            return True
        for attr in getattr(doc, "attributes", []):
            fn = (getattr(attr, "file_name", "") or "").lower()
            if fn.endswith(".pdf"):
                return True
    return False

def build_startup_banner(
    *,
    telegram_connected: bool = True,
    connected_providers: list[str] | None = None,
    memory_active: bool = True,
    voice_ready: bool = False,
    research_ready: bool = True,
    boss_verified: bool = True,
) -> str:
    """Build dynamic startup banner reflecting actual active system components."""
    lines = [
        "=====================",
        "ARU AI v2 ONLINE",
    ]
    if telegram_connected:
        lines.append("Telegram Connected")
    else:
        lines.append("Telegram Disconnected")

    if connected_providers:
        for prov_label in connected_providers:
            lines.append(f"{prov_label} Connected")
    else:
        lines.append("AI System Offline")

    if memory_active:
        lines.append("Memory System Active")
    if voice_ready:
        lines.append("Voice Assistant Ready")
    if research_ready:
        lines.append("Research Agent Ready")
    if boss_verified:
        lines.append("Boss Verification Active")
    lines.append("=====================")
    return "\n" + "\n".join(lines) + "\n"


BANNER = build_startup_banner(
    telegram_connected=True,
    connected_providers=["AI"],
    memory_active=True,
    voice_ready=True,
    research_ready=True,
    boss_verified=True,
)


class AruBot:
    """Telegram UserBot orchestrator."""

    def __init__(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        self.activity = ActivityLogger()
        self.client = TelegramClient(
            str(SESSION_PATH),
            TG_API_ID,
            TG_API_HASH,
            connection_retries=10,
            retry_delay=5,
            auto_reconnect=True,
        )
        self.ai = AruAI()
        self.memory = MemoryStore(activity=self.activity)
        self.conversation_store = ConversationHistoryStore(db_path=self.memory.db_path)
        self.memory_service = MemoryService(
            memory_store=self.memory,
            conversation_store=self.conversation_store,
            activity=self.activity,
        )
        self.anti_spam = AntiSpamManager(activity=self.activity)
        self.tasks = TaskManager(activity=self.activity)
        self.research = ResearchAgent(self.ai, activity=self.activity)
        self.voice = VoiceAssistant(self.ai, activity=self.activity)
        self.browser = BrowserAutomation()
        self.pdf_processor = PDFProcessor(provider_manager=self.ai.provider_manager)

        # Sprint 4: Unified Tool Registry & MCP Integration
        self.tool_manager = ToolManager(activity=self.activity)
        self.tool_manager.register_tool(BrowserTool(activity=self.activity))
        self.tool_manager.register_tool(FileReaderTool(root_dir=ROOT_DIR, activity=self.activity))
        self.tool_manager.register_tool(ResearchTool(research_service=self.research.service, activity=self.activity))
        self.tool_manager.register_tool(MemoryTool(memory_service=self.memory_service, activity=self.activity))
        self.tool_manager.register_tool(TaskTool(task_manager=self.tasks, activity=self.activity))

        # Autonomous Agent (ReAct + Tool Calling)
        self.agent = AruAgent(
            ai=self.ai,
            tool_manager=self.tool_manager,
            activity=self.activity,
            max_iterations=AGENT_MAX_ITERATIONS,
        )

        # Multi-Agent Autonomous Automation (Sprint 6)
        self.scheduler: AruScheduler | None = None
        self.multi_agent_manager = MultiAgentManager(
            ai=self.ai,
            tool_manager=self.tool_manager,
            scheduler=self.scheduler,
            activity=self.activity,
        )

        self._telegram_ok = False
        self._ai_ok = False
        self._provider_health: dict[str, bool] = {}
        self._voice_ok = False
        self._groq_ok = False

    async def send_to_boss(self, text: str) -> None:
        """Send message to Boss (scheduled jobs, reports)."""
        if not BOSS_TELEGRAM_ID:
            return
        try:
            await self.client.send_message(BOSS_TELEGRAM_ID, text)
            logger.info("Message sent to Boss (scheduled)")
        except Exception as exc:
            logger.exception("Failed to send to Boss: %s", exc)
            self.activity.log_error("system", "send_to_boss", exc)

    async def startup_checks(self) -> bool:
        reload_settings()
        problems = validate_config()
        if problems:
            logger.error("Configuration problems: %s", problems)
            print("\n❌ Configuration error(s):")
            for p in problems:
                print(f"   • {p}")
            status = env_file_status()
            empty_keys = [k for k, v in status.items() if v == "empty" and not k.startswith("_")]
            if empty_keys:
                print(f"\n   Your {ENV_PATH} has keys but EMPTY values on disk.")
                print("   -> Save the file in your editor (Ctrl+S), then run again.")
            elif status.get("_file") == "missing":
                print(f"\n   Copy {ROOT_DIR / '.env.example'} to {ENV_PATH}")
            print()
            return False

        logger.info("Environment OK | Boss ID=%s", BOSS_TELEGRAM_ID)
        self._ai_ok = self.ai.connect()
        self._groq_ok = "groq" in self.ai.provider_manager.get_enabled_providers()
        self._voice_ok = self.voice.connect()
        self.memory.list_all(limit=1)  # ensure DB loaded
        wal_mode = ensure_db_ready(self.memory.db_path)
        self.activity.log("system", "startup", "Aru AI v2 initialized")
        logger.info("SQLite ready at %s (journal_mode=%s)", self.memory.db_path, wal_mode)
        logger.info("Logging active at %s", LOGS_DIR / "aru.log")
        return True

    def _register_handlers(self) -> None:
        @self.client.on(events.NewMessage(incoming=True))
        async def on_incoming(event: events.NewMessage.Event) -> None:
            await self._handle_message(event, is_mention=False)

        @self.client.on(events.NewMessage(outgoing=True))
        async def on_outgoing(event: events.NewMessage.Event) -> None:
            # Only process outgoing private Saved Messages chat with self.
            if not event.is_private:
                return

            me = await self.client.get_me()
            if not me or event.chat_id != me.id:
                return

            await self._handle_message(event, is_mention=False, outgoing=True)

        @self.client.on(events.NewMessage(pattern=r"@\w+", incoming=True))
        async def on_mention(event: events.NewMessage.Event) -> None:
            me = await self.client.get_me()
            if me and me.username and f"@{me.username}".lower() in (event.raw_text or "").lower():
                await self._handle_message(event, is_mention=True)

    async def _handle_message(
        self,
        event: events.NewMessage.Event,
        *,
        is_mention: bool,
        outgoing: bool = False,
    ) -> None:
        try:
            if not event.is_private and not is_mention:
                return

            text = (event.raw_text or "").strip()
            is_voice = bool(event.message.voice or event.message.audio)
            is_image = is_image_message(event.message)
            is_pdf = is_pdf_message(event.message)

            if not text and not is_voice and not is_image and not is_pdf:
                return

            sender = await event.get_sender()
            authorized, sender_id = verify_sender(sender or event.sender_id)
            is_boss = authorized
            stripped = text.strip()
            lower = stripped.lower()
            command_detected = stripped.startswith("/")
            boss_only_command = any(
                lower.startswith(prefix)
                for prefix in (
                    "/research",
                    "/remember",
                    "/memories",
                    "/forget",
                    "/searchmemory",
                    "/task",
                    "/status",
                    "/unlock",
                    "/cooldown",
                    "/memory",
                    "/remind",
                    "/tools",
                    "/tool",
                    "/mcp",
                    "/agent",
                    "/plan",
                    "/workflow",
                    "/workflows",
                )
            )

            logger.debug(
                "Telegram event | chat_id=%s sender_id=%s is_private=%s is_boss=%s command_detected=%s boss_only=%s out=%s boss_id=%s len=%s",
                event.chat_id,
                sender_id,
                event.is_private,
                is_boss,
                command_detected,
                boss_only_command,
                event.out,
                BOSS_TELEGRAM_ID,
                len(text),
            )

            logger.info(
                "Message received | chat=%s sender=%s mention=%s voice=%s is_private=%s out=%s len=%s",
                event.chat_id,
                sender_id,
                is_mention,
                is_voice,
                event.is_private,
                event.out,
                len(text),
            )

            if not authorized:
                should_reply, reason = self.anti_spam.should_reply(sender_id, is_boss=False)
                if should_reply:
                    await event.reply(unauthorized_message())
                    self.anti_spam.record_reply(sender_id, is_boss=False)
                    logger.info(
                        "Unauthorized reply sent | sender=%s chat=%s reason=%s",
                        sender_id,
                        event.chat_id,
                        reason,
                    )
                else:
                    self.anti_spam.record_ignored_message(sender_id)
                    logger.info(
                        "Unauthorized message ignored | sender=%s chat=%s reason=%s message_count=%s",
                        sender_id,
                        event.chat_id,
                        reason,
                        self.anti_spam.get_cooldown_info(sender_id).message_count if self.anti_spam.get_cooldown_info(sender_id) else 0,
                    )
                return

            if is_mention and event.is_private:
                return

            if is_voice:
                await self._handle_voice_message(event, event.chat_id)
                return

            if is_image:
                await self._handle_image_message(event, event.chat_id, text)
                return

            if is_pdf:
                await self._handle_pdf_message(event, event.chat_id, text)
                return

            response = await self._process_boss_message(event, text, event.chat_id, sender_id)
            if response:
                await event.reply(response)
                logger.info(
                    "Message sent | chat=%s len=%s reply_generated=%s",
                    event.chat_id,
                    len(response),
                    True,
                )

        except FloodWaitError as exc:
            logger.warning("Flood wait %s seconds", exc.seconds)
            await asyncio.sleep(exc.seconds)
        except Exception as exc:
            logger.exception("Handler error: %s", exc)
            self.activity.log_error("system", "handler", exc)
            try:
                await event.reply(
                    "দুঃখিত বস, একটি ত্রুটি হয়েছে। আমি লগে রেকর্ড করেছি — একটু পরে আবার চেষ্টা করুন।"
                )
            except Exception:
                pass

    async def _handle_voice_message(
        self,
        event: events.NewMessage.Event,
        chat_id: int,
    ) -> None:
        """Download voice note, transcribe, and reply with AI response."""
        if not self._voice_ok:
            await event.reply("ভয়েস অ্যাসিস্ট্যান্ট এখন উপলব্ধ নয়। Groq API চেক করুন।")
            return

        try:
            audio_bytes = await event.message.download_media(bytes)
            if not audio_bytes:
                await event.reply("ভয়েস ফাইল ডাউনলোড করতে পারিনি।")
                return

            history = self.memory_service.get_conversation_context(chat_id)
            transcript, reply = await self.voice.process_voice_message(
                audio_bytes,
                memory=self.memory,
                conversation_history=history,
            )

            if transcript:
                self.memory_service.record_interaction(
                    chat_id,
                    user_message=f"[Voice] {transcript}",
                    assistant_reply=reply,
                )
                response = f"🎤 **Transcript:** {transcript}\n\n{reply}"
            else:
                response = reply

            await event.reply(response)
            logger.info("Voice response sent | chat=%s reply_generated=%s", chat_id, True)

        except Exception as exc:
            logger.exception("Voice handler error: %s", exc)
            self.activity.log_error("voice", "handle", exc)
            await event.reply(
                "ভয়েস প্রসেস করতে সমস্যা হয়েছে। আবার চেষ্টা করুন বা টেক্সটে লিখুন।"
            )

    async def _handle_image_message(
        self,
        event: events.NewMessage.Event,
        chat_id: int,
        prompt: str = "",
    ) -> None:
        """Download image, analyze with vision provider failover (Gemini Vision primary), and reply."""
        try:
            status_msg = await event.reply("🖼️ ছবিটি দেখা হচ্ছে, একটু অপেক্ষা করুন...")
            reply = await process_image_message(
                message=event.message,
                user_prompt=prompt,
                provider_manager=self.ai.provider_manager,
            )
            self.memory_service.record_interaction(
                chat_id,
                user_message=f"[Image: {prompt or 'ছবি বিশ্লেষণ'}]",
                assistant_reply=reply,
            )
            try:
                await status_msg.delete()
            except Exception:
                pass
            await event.reply(reply)
            logger.info("Image response sent | chat=%s reply_len=%s", chat_id, len(reply))
        except Exception as exc:
            logger.exception("Image handler error: %s", exc)
            self.activity.log_error("vision", "handle", exc)
            await event.reply("ছবিটি বিশ্লেষণ করতে সমস্যা হয়েছে। দয়া করে আবার চেষ্টা করুন।")

    async def _handle_pdf_message(
        self,
        event: events.NewMessage.Event,
        chat_id: int,
        prompt: str = "",
    ) -> None:
        """Download PDF, chunk, progressively summarize across failover providers, and reply."""
        try:
            status_msg = await event.reply("📄 PDF ফাইল প্রসেস করা হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
            pdf_bytes = await event.message.download_media(bytes)
            if not pdf_bytes:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                await event.reply("PDF ডাউনলোড করতে পারিনি। অনুগ্রহ করে আবার চেষ্টা করুন।")
                return

            user_query = prompt or "Summarize the key information and outline main points from this document."
            summary = await self.pdf_processor.summarize_pdf(pdf_bytes, prompt=user_query)

            self.memory_service.record_interaction(
                chat_id,
                user_message=f"[PDF: {user_query}]",
                assistant_reply=summary,
            )
            try:
                await status_msg.delete()
            except Exception:
                pass

            await event.reply(summary)
            logger.info("PDF response sent | chat=%s summary_len=%s", chat_id, len(summary))
        except Exception as exc:
            logger.exception("PDF handler error: %s", exc)
            self.activity.log_error("pdf", "handle", exc)
            await event.reply("PDF ফাইলটি প্রসেস করতে সমস্যা হয়েছে। দয়া করে আবার চেষ্টা করুন।")

    async def _process_boss_message(
        self,
        event: events.NewMessage.Event,
        text: str,
        chat_id: int,
        sender_id: int,
    ) -> str | None:
        """Route commands or forward to AI."""
        lower = text.lower()

        if lower.startswith("/unlock"):
            code = text.split(maxsplit=1)[1] if len(text.split()) > 1 else ""
            if verify_secret_code(code):
                return "সিক্রেট কোড যাচাই সফল ✅"
            return "ভুল সিক্রেট কোড।"

        if lower in ("/clearchat", "/clearhistory"):
            cleared = self.memory_service.clear_conversation(chat_id)
            return f"কথোপকথনের ইতিহাস মুছে ফেলা হয়েছে ({cleared}টি মেসেজ) 🗑️"

        research_result = await self.research.handle_command_async(
            text, memory=self.memory
        )
        if research_result is not None:
            return research_result

        tools_result = await handle_tools_command(
            text,
            self.tool_manager,
            ExecutionContext(user_id=sender_id, is_boss=True, caller="telegram"),
        )
        if tools_result is not None:
            return tools_result

        plan_result = await handle_plan_command(
            text,
            self.multi_agent_manager,
            ExecutionContext(user_id=sender_id, is_boss=True, caller="telegram"),
        )
        if plan_result is not None:
            return plan_result

        workflow_result = await handle_workflow_command(
            text,
            self.multi_agent_manager,
            ExecutionContext(user_id=sender_id, is_boss=True, caller="telegram"),
        )
        if workflow_result is not None:
            return workflow_result

        agent_result = await handle_agent_command(
            text,
            self.agent,
            ExecutionContext(user_id=sender_id, is_boss=True, caller="telegram"),
            manager=self.multi_agent_manager,
        )
        if agent_result is not None:
            return agent_result

        for result in (
            handle_cooldown_command(text, self.anti_spam, sender_id),
            handle_help_command(text),
            self.tasks.handle_command(text),
            self.memory.handle_v2_command(text),
            handle_memory_command(text, self.memory),
            handle_reminder_command(text, self.scheduler) if self.scheduler else None,
            handle_status_command(
                text,
                telegram_ok=self._telegram_ok,
                groq_ok=self._groq_ok,
                memory_count=len(self.memory.list_all(limit=500)),
                pending_tasks=self.tasks.pending_count(),
                voice_ok=self._voice_ok,
                activity_count=self.activity.count(),
                tools_count=len(self.tool_manager.get_tool_names()),
                multi_agents_count=len(self.multi_agent_manager._agents),
                workflows_count=len(self.multi_agent_manager._workflows),
                llm_status=(
                    self.ai.provider_manager.format_status_summary()
                    if hasattr(self.ai, "provider_manager") and self.ai.provider_manager
                    else None
                ),
            ),
        ):
            if result is not None:
                return result

        memory_ctx = self.memory_service.build_context_for_prompt(text)
        history = self.memory_service.get_conversation_context(chat_id)
        agent_resp = await self.agent.run(
            text,
            context=ExecutionContext(user_id=sender_id, is_boss=True, caller="telegram"),
            memory_context=memory_ctx,
            conversation_history=history,
        )
        reply = agent_resp.reply

        self.memory_service.record_interaction(chat_id, user_message=text, assistant_reply=reply)
        return reply

    async def run(self) -> None:
        if not await self.startup_checks():
            sys.exit(1)

        self._register_handlers()

        session_file = Path(str(SESSION_PATH) + ".session")
        if not session_file.exists():
            print(
                "\n📱 First-time Telegram login required.\n"
                "   Enter your phone number and login code when prompted below.\n"
            )

        self._provider_health = {}
        if self._ai_ok:
            enabled_providers = self.ai.provider_manager.get_enabled_providers()
            logger.info("Verifying LLM provider connectivity (enabled: %s)...", ", ".join(enabled_providers) or "None")
            display_names = {
                "openrouter": "OpenRouter",
                "openai": "OpenRouter",
                "groq": "Groq",
                "gemini": "Gemini",
                "cloudflare": "Cloudflare",
                "deepseek": "DeepSeek",
            }
            # health_check_all() only pings enabled providers, skips disabled ones
            self._provider_health = await self.ai.provider_manager.health_check_all()
            for p_name in enabled_providers:
                p_label = display_names.get(p_name, p_name.capitalize())
                is_healthy = self._provider_health.get(p_name, False)
                p_obj = self.ai.provider_manager.get_provider(p_name)
                active_model = getattr(p_obj, "active_model", getattr(p_obj, "default_model", ""))
                if is_healthy:
                    logger.info("%s health check passed (model=%s)", p_label, active_model)
                else:
                    logger.warning("%s health check failed or timed out", p_label)

        # Update legacy _groq_ok flag based on actual Groq health check
        self._groq_ok = self._provider_health.get("groq", False)

        logger.info("Starting Telegram client...")
        await self.client.connect()
        if not await self.client.is_user_authorized():
            print("Telegram: starting interactive login...")
            try:
                await self.client.start()
            except EOFError:
                logger.error("Telegram login requires interactive terminal (EOF)")
                print(
                    "\n❌ Telegram login needs an interactive terminal.\n"
                    "   Run in Cursor terminal:  python main.py\n"
                    "   Then enter your phone number and Telegram code.\n"
                )
                await self.client.disconnect()
                return

        self._telegram_ok = await self.client.is_user_authorized()
        if not self._telegram_ok:
            logger.error("Telegram login failed")
            print("❌ Telegram authorization failed. Run again and complete login.")
            return

        me = await self.client.get_me()
        logger.info("Login success as %s (id=%s)", me.username or me.first_name, me.id)

        self.scheduler = AruScheduler(
            self.send_to_boss,
            self.tasks,
            self.memory,
        )
        self.scheduler.start()
        self.multi_agent_manager.scheduler = self.scheduler
        sched_agent = self.multi_agent_manager.get_agent("scheduler")
        if sched_agent is not None:
            sched_agent.scheduler = self.scheduler

        display_names = {
            "openrouter": "OpenRouter",
            "openai": "OpenRouter",
            "groq": "Groq",
            "gemini": "Gemini",
            "cloudflare": "Cloudflare",
            "deepseek": "DeepSeek",
        }
        connected_providers: list[str] = []
        for p_name in self.ai.provider_manager.priority:
            if p_name in self.ai.provider_manager.get_enabled_providers():
                if self._provider_health.get(p_name, False):
                    label = display_names.get(p_name, p_name.capitalize())
                    connected_providers.append(label)

        # Fallback if health checks timed out but provider is enabled and AI connected
        if not connected_providers and self._ai_ok:
            for p_name in self.ai.provider_manager.get_enabled_providers():
                label = display_names.get(p_name, p_name.capitalize())
                connected_providers.append(label)

        banner = build_startup_banner(
            telegram_connected=self._telegram_ok,
            connected_providers=connected_providers,
            memory_active=True,
            voice_ready=self._voice_ok,
            research_ready=bool(self.research),
            boss_verified=bool(BOSS_TELEGRAM_ID),
        )
        print(banner)
        logger.info("Aru AI v2 is online and listening")

        try:
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        self.multi_agent_manager.shutdown()
        if self.scheduler:
            self.scheduler.shutdown()
        await self.browser.stop()
        self.activity.log("system", "shutdown", "Aru AI v2 stopped")
        if self.client.is_connected():
            await self.client.disconnect()
        logger.info("Aru shutdown complete")


def main() -> None:
    bot = AruBot()
    try:
        asyncio.run(bot.run())
    except SessionPasswordNeededError:
        logger.error("2FA enabled — complete login in terminal when prompted")
        print("2FA required. Run `python main.py` in terminal and enter password.")
        sys.exit(1)
    except RPCError as exc:
        logger.exception("Telegram RPC error: %s", exc)
        sys.exit(1)
    except EOFError:
        logger.error("Interactive input required for Telegram login")
        print(
            "\n❌ Run `python main.py` in an interactive terminal "
            "to complete Telegram phone/code login.\n"
        )
        sys.exit(1)
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
