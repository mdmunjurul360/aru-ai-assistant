"""ARU AI V4 — Production Application Bootstrap and Lifecycle Orchestrator."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path
from typing import Any, Callable

# Ensure src/ is on sys.path for direct python src/aru/app.py execution
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aru.brain.interfaces import ILLMProvider
from aru.brain.models import LLMMessage
from aru.brain.providers.cloudflare_provider import CloudflareProvider
from aru.brain.providers.deepseek_provider import DeepSeekProvider
from aru.brain.providers.groq_provider import GroqProvider
from aru.brain.providers.openrouter_provider import OpenRouterProvider
from aru.brain.router import LLMRouter
from aru.core.config.loader import get_settings, load_settings
from aru.core.config.models import AppSettings
from aru.core.di.container import Container
from aru.core.logging.service import StructuredLogger, setup_v4_logging
from aru.database.connection import DatabaseManager
from aru.database.migrations.runner import MigrationRunner
from aru.database.repositories.anti_spam_repo import AntiSpamRepository
from aru.database.repositories.conversation_repo import ConversationRepository
from aru.database.repositories.memory_repo import MemoryRepository
from aru.database.repositories.task_repo import TaskRepository
from aru.executor.engine import PlanExecutor
from aru.executor.reflection import ReflectionEngine
from aru.interfaces.telegram.client import TelegramClientManager
from aru.interfaces.telegram.dispatcher import TelegramDispatcher
from aru.interfaces.telegram.handlers.callback import CallbackHandler
from aru.interfaces.telegram.handlers.command import CommandHandler
from aru.interfaces.telegram.handlers.media import MediaHandler
from aru.interfaces.telegram.handlers.message import MessageHandler
from aru.interfaces.telegram.handlers.voice import VoiceHandler
from aru.interfaces.telegram.middleware.anti_spam import AntiSpamMiddleware
from aru.interfaces.telegram.middleware.auth import AuthMiddleware
from aru.interfaces.telegram.middleware.logging import LoggingMiddleware
from aru.interfaces.telegram.middleware.rate_limit import RateLimitMiddleware
from aru.memory.persistent_memory import PersistentMemory
from aru.memory.service import MemoryService
from aru.memory.working_memory import WorkingMemory
from aru.planner.decomposer import GoalDecomposer
from aru.planner.react import ReActPlanner
from aru.planner.replanner import Replanner
from aru.services.cleanup import CleanupService
from aru.services.database_maintenance import DatabaseMaintenanceService
from aru.services.health_monitor import HealthMonitorService
from aru.services.heartbeat import HeartbeatService
from aru.services.reminder import ReminderService
from aru.services.scheduler import SchedulerService
from aru.tools.builtin.calculator_tool import CalculatorTool
from aru.tools.builtin.file_reader_tool import FileReaderTool
from aru.tools.builtin.memory_tool import MemoryTool
from aru.tools.builtin.web_search_tool import WebSearchTool
from aru.tools.executor import ToolExecutor
from aru.tools.registry import ToolRegistry


def build_container(settings: AppSettings) -> Container:
    """
    Construct and wire the complete IoC Dependency Injection Container for ARU AI V4.
    """
    container = Container()

    # 1. Configuration & Logging
    container.register_instance(AppSettings, settings)
    logger = StructuredLogger("aru.app")
    container.register_instance(StructuredLogger, logger)

    # 2. Database & Migrations
    db_manager = DatabaseManager(settings.system.database_path)
    container.register_instance(DatabaseManager, db_manager)
    migration_runner = MigrationRunner(db_manager)
    container.register_instance(MigrationRunner, migration_runner)

    # 3. Repositories
    conversation_repo = ConversationRepository(db_manager)
    container.register_instance(ConversationRepository, conversation_repo)

    memory_repo = MemoryRepository(db_manager)
    container.register_instance(MemoryRepository, memory_repo)

    task_repo = TaskRepository(db_manager)
    container.register_instance(TaskRepository, task_repo)

    anti_spam_repo = AntiSpamRepository(db_manager)
    container.register_instance(AntiSpamRepository, anti_spam_repo)

    # 4. Memory System
    working_memory = WorkingMemory(
        default_max_messages=settings.scheduler.conversation_history_limit
    )
    container.register_instance(WorkingMemory, working_memory)

    persistent_memory = PersistentMemory(memory_repo)
    container.register_instance(PersistentMemory, persistent_memory)

    memory_service = MemoryService(
        working_memory=working_memory,
        persistent_memory=persistent_memory,
    )
    container.register_instance(MemoryService, memory_service)

    # 5. Tool System
    tool_registry = ToolRegistry()
    container.register_instance(ToolRegistry, tool_registry)

    # Register built-in tools
    tool_registry.register(CalculatorTool())
    tool_registry.register(FileReaderTool(root_dir=settings.system.root_dir))
    tool_registry.register(MemoryTool(memory_service=memory_service))
    tool_registry.register(WebSearchTool())

    tool_executor = ToolExecutor(registry=tool_registry)
    container.register_instance(ToolExecutor, tool_executor)

    # 6. Brain & LLM Router
    router = LLMRouter(settings=settings)

    # Instantiate configured LLM providers
    # Groq
    if settings.llm.groq_api_keys:
        groq_keys = [k.get_secret_value() for k in settings.llm.groq_api_keys if k.get_secret_value()]
        if groq_keys:
            router.register_provider(
                GroqProvider(
                    api_keys=groq_keys,
                    default_model=settings.llm.groq_model,
                    default_timeout=settings.llm.timeout,
                )
            )

    # OpenRouter
    if settings.llm.openrouter_api_keys:
        or_keys = [k.get_secret_value() for k in settings.llm.openrouter_api_keys if k.get_secret_value()]
        if or_keys:
            router.register_provider(
                OpenRouterProvider(
                    api_keys=or_keys,
                    default_model=settings.llm.openrouter_model,
                    default_timeout=settings.llm.timeout,
                )
            )

    # DeepSeek
    if settings.llm.deepseek_api_keys:
        ds_keys = [k.get_secret_value() for k in settings.llm.deepseek_api_keys if k.get_secret_value()]
        if ds_keys:
            router.register_provider(
                DeepSeekProvider(
                    api_keys=ds_keys,
                    default_timeout=settings.llm.timeout,
                )
            )

    # Cloudflare
    if settings.llm.cloudflare_accounts:
        cf_accounts = [
            {"account_id": a.account_id, "api_key": a.api_key.get_secret_value()}
            for a in settings.llm.cloudflare_accounts
            if a.account_id and a.api_key.get_secret_value()
        ]
        if cf_accounts:
            router.register_provider(
                CloudflareProvider(
                    accounts=cf_accounts,
                    default_timeout=settings.llm.timeout,
                )
            )

    container.register_instance(LLMRouter, router)

    # 7. Planner Layer
    goal_decomposer = GoalDecomposer(tool_registry=tool_registry, router=router)
    container.register_instance(GoalDecomposer, goal_decomposer)

    react_planner = ReActPlanner(tool_registry=tool_registry, router=router)
    container.register_instance(ReActPlanner, react_planner)

    replanner = Replanner()
    container.register_instance(Replanner, replanner)

    # 8. Executor Layer
    reflection_engine = ReflectionEngine()
    container.register_instance(ReflectionEngine, reflection_engine)

    plan_executor = PlanExecutor(
        tool_executor=tool_executor,
        max_iterations=settings.agent.max_iterations,
        timeout_seconds=settings.agent.timeout_seconds,
        enable_replanning=True,
    )
    container.register_instance(PlanExecutor, plan_executor)

    # 9. Background Services Layer
    scheduler = SchedulerService()
    container.register_instance(SchedulerService, scheduler)

    heartbeat = HeartbeatService(scheduler=scheduler)
    container.register_instance(HeartbeatService, heartbeat)

    maintenance = DatabaseMaintenanceService(db_manager=db_manager, scheduler=scheduler)
    container.register_instance(DatabaseMaintenanceService, maintenance)

    cleanup = CleanupService(settings=settings, scheduler=scheduler)
    container.register_instance(CleanupService, cleanup)

    health_monitor = HealthMonitorService(
        db_manager=db_manager,
        settings=settings,
        router=router,
        scheduler=scheduler,
    )
    container.register_instance(HealthMonitorService, health_monitor)

    reminder = ReminderService(scheduler=scheduler, task_repo=task_repo)
    container.register_instance(ReminderService, reminder)

    # 10. Telegram Interface Layer
    cmd_handler = CommandHandler(memory_service=memory_service, task_repo=task_repo)
    container.register_instance(CommandHandler, cmd_handler)

    msg_handler = MessageHandler(
        memory_service=memory_service,
        goal_decomposer=goal_decomposer,
        plan_executor=plan_executor,
        router=router,
    )
    container.register_instance(MessageHandler, msg_handler)

    callback_handler = CallbackHandler()
    container.register_instance(CallbackHandler, callback_handler)

    media_handler = MediaHandler()
    container.register_instance(MediaHandler, media_handler)

    voice_handler = VoiceHandler()
    container.register_instance(VoiceHandler, voice_handler)

    dispatcher = TelegramDispatcher(
        command_handler=cmd_handler,
        message_handler=msg_handler,
        callback_handler=callback_handler,
        media_handler=media_handler,
        voice_handler=voice_handler,
    )
    # Register middleware pipeline
    dispatcher.use(LoggingMiddleware())
    dispatcher.use(RateLimitMiddleware(anti_spam_repo=anti_spam_repo))
    dispatcher.use(AntiSpamMiddleware(anti_spam_repo=anti_spam_repo))
    dispatcher.use(AuthMiddleware(settings=settings, anti_spam_repo=anti_spam_repo))
    container.register_instance(TelegramDispatcher, dispatcher)

    client_manager = TelegramClientManager(settings=settings, dispatcher=dispatcher)
    container.register_instance(TelegramClientManager, client_manager)

    return container


class AruApplication:
    """
    ARU AI V4 Master Application runtime controller managing lifecycle startup,
    background services, database migrations, and clean shutdowns.
    """

    def __init__(self, container: Container) -> None:
        self.container = container
        self.settings: AppSettings = container.resolve(AppSettings)
        self.logger: StructuredLogger = container.resolve(StructuredLogger)
        self.db_manager: DatabaseManager = container.resolve(DatabaseManager)
        self.migration_runner: MigrationRunner = container.resolve(MigrationRunner)
        self.conversation_repo: ConversationRepository = container.resolve(ConversationRepository)
        self.memory_repo: MemoryRepository = container.resolve(MemoryRepository)
        self.task_repo: TaskRepository = container.resolve(TaskRepository)
        self.anti_spam_repo: AntiSpamRepository = container.resolve(AntiSpamRepository)
        self.memory_service: MemoryService = container.resolve(MemoryService)
        self.tool_registry: ToolRegistry = container.resolve(ToolRegistry)
        self.tool_executor: ToolExecutor = container.resolve(ToolExecutor)
        self.llm_router: LLMRouter = container.resolve(LLMRouter)
        self.goal_decomposer: GoalDecomposer = container.resolve(GoalDecomposer)
        self.react_planner: ReActPlanner = container.resolve(ReActPlanner)
        self.replanner: Replanner = container.resolve(Replanner)
        self.reflection_engine: ReflectionEngine = container.resolve(ReflectionEngine)
        self.plan_executor: PlanExecutor = container.resolve(PlanExecutor)
        self.scheduler: SchedulerService = container.resolve(SchedulerService)
        self.heartbeat: HeartbeatService = container.resolve(HeartbeatService)
        self.maintenance: DatabaseMaintenanceService = container.resolve(DatabaseMaintenanceService)
        self.cleanup: CleanupService = container.resolve(CleanupService)
        self.health_monitor: HealthMonitorService = container.resolve(HealthMonitorService)
        self.reminder: ReminderService = container.resolve(ReminderService)
        self.dispatcher: TelegramDispatcher = container.resolve(TelegramDispatcher)
        self.client_manager: TelegramClientManager = container.resolve(TelegramClientManager)

        self._is_running = False
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._is_running

    @classmethod
    def create(cls, settings: AppSettings | None = None) -> AruApplication:
        """Factory method to construct an initialized AruApplication instance."""
        active_settings = settings or get_settings()
        container = build_container(active_settings)
        return cls(container)

    async def startup(self, start_telegram: bool = True, start_scheduler: bool = True) -> None:
        """
        Execute full asynchronous application startup sequence:
        1. Setup logging
        2. Execute database migrations
        3. Connect database connection pool
        4. Register and start background maintenance/health/heartbeat schedules
        5. Connect and initialize Telegram client (if configured)
        """
        self.logger.info("Initializing ARU AI V4 (Environment: %s)...", self.settings.system.environment)

        # 1. Setup logging
        setup_v4_logging(self.settings)

        # 2. Database migrations
        self.logger.info("Applying database migrations on %s...", self.settings.system.database_path)
        applied_migrations = await self.migration_runner.run()
        self.logger.info("Applied %d database migration(s) successfully.", len(applied_migrations))

        # 3. Connect DB
        await self.db_manager.connect()

        # 4. Background services
        if start_scheduler:
            self.logger.info("Scheduling automated background routines...")
            self.heartbeat.start_scheduled()
            self.maintenance.schedule_maintenance()
            self.cleanup.schedule_nightly_cleanup()
            self.health_monitor.schedule_health_checks()
            self.reminder.schedule_due_task_scanner()

            # Wire reminder delivery to boss telegram sender
            self.reminder.set_notifier(
                lambda msg, chat_id: self.client_manager.send_to_boss(msg)
            )

            self.scheduler.start()

        # 5. Telegram Client
        if start_telegram and self.settings.telegram.is_configured:
            self.logger.info("Starting Telegram client interface...")
            try:
                authorized = await self.client_manager.start(interactive=False)
                if not authorized:
                    self.logger.warning("Telegram client started in unauthorized/passive mode.")
            except Exception as exc:
                self.logger.warning("Could not connect to Telegram client: %s", exc)

        self._is_running = True
        self.logger.info("ARU AI V4 Startup Complete. All systems operational.")

    async def shutdown(self) -> None:
        """
        Gracefully stop all services and release resources in reverse dependency order.
        """
        self.logger.info("Initiating graceful shutdown of ARU AI V4...")
        self._is_running = False
        self._stop_event.set()

        # 1. Disconnect Telegram client
        if self.client_manager.is_connected:
            self.logger.info("Stopping Telegram client...")
            try:
                await self.client_manager.stop()
            except Exception as exc:
                self.logger.warning("Error stopping Telegram client: %s", exc)

        # 2. Stop Heartbeat & Background Scheduler
        if self.scheduler.is_running:
            self.logger.info("Stopping background scheduler...")
            try:
                await self.heartbeat.stop()
                self.scheduler.shutdown(wait=False)
            except Exception as exc:
                self.logger.warning("Error shutting down scheduler: %s", exc)

        # 3. Disconnect Database
        if self.db_manager.is_connected:
            self.logger.info("Disconnecting database...")
            try:
                await self.db_manager.disconnect()
            except Exception as exc:
                self.logger.warning("Error disconnecting database: %s", exc)

        self.logger.info("ARU AI V4 Shutdown Complete.")

    def _setup_signal_handlers(self) -> None:
        """Register cross-platform POSIX and Windows signal handlers."""
        loop = asyncio.get_running_loop()

        def _signal_handler() -> None:
            self.logger.info("Termination signal received. Triggering graceful shutdown...")
            self._stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except (NotImplementedError, AttributeError):
                # Fallback for Windows Proactor event loop
                signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(self._stop_event.set))

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """
        Run the application until an external stop event, signal, or cancellation occurs.
        """
        await self.startup()
        self._setup_signal_handlers()

        target_event = stop_event or self._stop_event
        try:
            await target_event.wait()
        finally:
            await self.shutdown()


async def main() -> None:
    """Production CLI entry point for ARU AI V4."""
    app = AruApplication.create()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
