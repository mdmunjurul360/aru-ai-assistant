"""Strongly typed Pydantic models for V4 configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class TelegramSettings(BaseModel):
    """Telegram client credentials and identity settings."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    api_id: int = Field(default=0, description="Telegram App API ID")
    api_hash: SecretStr = Field(default=SecretStr(""), description="Telegram App API Hash")
    bot_token: SecretStr = Field(default=SecretStr(""), description="Telegram Bot Token (optional)")
    bot_id: int = Field(default=0, description="Telegram Bot numeric ID")
    telegram_secret: SecretStr = Field(default=SecretStr(""), description="Telegram Secret token")
    boss_telegram_id: int = Field(default=0, description="Boss numeric user ID")
    secret_code: SecretStr = Field(default=SecretStr(""), description="Secret unlock code")
    unauthorized_reply: str = Field(
        default=(
            "দুঃখিত স্যার\n\n"
            "আমি Aru AI। আমি শুধুমাত্র আমার বস মঞ্জুরুলের নির্দেশ পালন করি।\n\n"
            "আপনার মেসেজটি গ্রহণ করা হয়েছে। আমার বস বর্তমানে ব্যস্ত আছেন। তিনি সময় পেলে আপনার সাথে যোগাযোগ করবেন।\n\n"
            "আপনার ধৈর্যের জন্য ধন্যবাদ। 💙"
        ),
        description="Auto-reply message for unauthorized users",
    )

    @property
    def is_configured(self) -> bool:
        """Check whether minimum required Telegram credentials are present."""
        return self.api_id > 0 and len(self.api_hash.get_secret_value()) > 0 and self.boss_telegram_id > 0


class CloudflareAccount(BaseModel):
    """Paired Cloudflare account identifier and API token."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    account_id: str
    api_key: SecretStr

    def __repr__(self) -> str:
        return f"CloudflareAccount(account_id='{self.account_id}', api_key='***')"


class LLMSettings(BaseModel):
    """Large Language Model providers, keys, and routing options."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    # Provider priorities & parameters
    priority: list[str] = Field(
        default=["openrouter", "groq", "gemini", "cloudflare", "deepseek"],
        description="Ordered provider failover list",
    )
    timeout: float = Field(default=30.0, ge=1.0, le=300.0, description="Request timeout in seconds")
    retry: int = Field(default=2, ge=0, le=10, description="Max retry attempts per provider")
    cooldown_seconds: float = Field(default=300.0, ge=0.0, description="Rate-limit cooldown period")

    # OpenRouter
    openrouter_api_keys: list[SecretStr] = Field(default_factory=list)
    openrouter_model: str = Field(default="openai/gpt-4o-mini")

    # Groq
    groq_api_keys: list[SecretStr] = Field(default_factory=list)
    groq_model: str = Field(default="qwen/qwen3.8-27b")
    groq_model_fallbacks: tuple[str, ...] = Field(
        default=(
            "qwen/qwen3.8-27b",
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
        )
    )

    # Gemini
    gemini_api_keys: list[SecretStr] = Field(default_factory=list)

    # DeepSeek
    deepseek_api_keys: list[SecretStr] = Field(default_factory=list)

    # OpenAI
    openai_api_keys: list[SecretStr] = Field(default_factory=list)

    # Cloudflare
    cloudflare_accounts: list[CloudflareAccount] = Field(default_factory=list)

    # System persona
    system_prompt: str = Field(
        default=(
            "You are Aru, the personal AI assistant of your Boss.\n"
            "You are loyal, intelligent, friendly, witty, helpful and professional.\n"
            "Always answer in the same language used by the Boss (Bangla or English).\n"
            "Remember Boss preferences and ongoing projects whenever relevant.\n"
            "Provide practical answers.\n"
            "Never be rude to the Boss.\n"
            "Act like a trusted assistant, planner and productivity partner."
        )
    )


class SchedulerSettings(BaseModel):
    """Background tasks, cron schedules, and retention policies."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    timezone: str = Field(default="Asia/Dhaka")
    morning_report_hour: int = Field(default=8, ge=0, le=23)
    morning_report_minute: int = Field(default=0, ge=0, le=59)
    night_summary_hour: int = Field(default=22, ge=0, le=23)
    night_summary_minute: int = Field(default=0, ge=0, le=59)
    maintenance_hour: int = Field(default=3, ge=0, le=23)
    maintenance_minute: int = Field(default=0, ge=0, le=59)
    log_retention_days: int = Field(default=30, ge=1)
    cooldown_retention_hours: int = Field(default=72, ge=1)
    conversation_history_limit: int = Field(default=20, ge=1, le=500)


class ResearchSettings(BaseModel):
    """Web search engines and research agent configuration."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    search_provider: Literal["duckduckgo", "tavily", "serper"] = Field(default="duckduckgo")
    tavily_api_key: SecretStr = Field(default=SecretStr(""))
    serper_api_key: SecretStr = Field(default=SecretStr(""))
    research_cache_ttl_seconds: int = Field(default=3600, ge=0)
    research_max_results: int = Field(default=5, ge=1, le=50)


class AgentSettings(BaseModel):
    """Autonomous agent execution constraints and iteration budgets."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    max_iterations: int = Field(default=5, ge=1, le=50)
    timeout_seconds: float = Field(default=90.0, ge=5.0, le=600.0)


class SystemSettings(BaseModel):
    """Filesystem directories, environment tier, and storage paths."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    environment: Literal["development", "production", "test"] = Field(default="development")
    root_dir: Path
    database_dir: Path
    database_path: Path
    logs_dir: Path
    log_file: Path
    sessions_dir: Path
    session_path: Path

    @classmethod
    def create_default(cls, root_dir: Path, env: str = "development") -> SystemSettings:
        db_dir = root_dir / "database"
        logs_dir = root_dir / "logs"
        sessions_dir = root_dir / "sessions"
        return cls(
            environment=env,  # type: ignore[arg-type]
            root_dir=root_dir,
            database_dir=db_dir,
            database_path=db_dir / "aru_v4.db",  # Isolated V4 database
            logs_dir=logs_dir,
            log_file=logs_dir / "aru_v4.log",    # Isolated V4 log file
            sessions_dir=sessions_dir,
            session_path=sessions_dir / "aru_v4",
        )


class AppSettings(BaseModel):
    """Root application configuration aggregating all domain settings."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    system: SystemSettings

    def __repr__(self) -> str:
        """Sanitized string representation masking all secrets."""
        return (
            f"AppSettings(environment='{self.system.environment}', "
            f"telegram_configured={self.telegram.is_configured}, "
            f"llm_priority={self.llm.priority}, "
            f"search_provider='{self.research.search_provider}', "
            f"db_path='{self.system.database_path}', "
            f"log_file='{self.system.log_file}')"
        )
