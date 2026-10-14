"""Configuration loader and factory for ARU AI V4."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping
from dotenv import dotenv_values
from pydantic import SecretStr

from aru.core.config.models import (
    AgentSettings,
    AppSettings,
    CloudflareAccount,
    LLMSettings,
    ResearchSettings,
    SchedulerSettings,
    SystemSettings,
    TelegramSettings,
)
from aru.core.config.parser import parse_api_keys, parse_cloudflare_credentials

_CACHED_SETTINGS: AppSettings | None = None


def _find_repo_root() -> Path:
    """Find repository root by looking for pyproject.toml or .git."""
    curr = Path(__file__).resolve()
    for parent in [curr] + list(curr.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    # Fallback to 4 levels up (src/aru/core/config/loader.py -> repo_root)
    return Path(__file__).resolve().parent.parent.parent.parent


def build_settings_from_mapping(
    env_map: Mapping[str, Any],
    root_dir: Path | None = None,
    yaml_config: Mapping[str, Any] | None = None,
) -> AppSettings:
    """Construct AppSettings from environment key-value mapping and optional YAML overrides."""
    root = root_dir or _find_repo_root()
    yaml_cfg = yaml_config or {}

    # Environment tier
    env_tier = str(env_map.get("ENVIRONMENT", "development")).lower()
    if env_tier not in ("development", "production", "test"):
        env_tier = "development"
    system_settings = SystemSettings.create_default(root, env=env_tier)

    # 1. Telegram
    tg_api_id = int(env_map.get("TG_API_ID") or env_map.get("TELEGRAM_API_ID") or 0)
    tg_api_hash = str(env_map.get("TG_API_HASH") or env_map.get("TELEGRAM_API_HASH") or "")
    tg_bot_token = str(env_map.get("TELEGRAM_BOT_TOKEN") or "")
    tg_bot_id = int(env_map.get("TELEGRAM_BOT_ID") or 0)
    tg_secret = str(env_map.get("TELEGRAM_SECRET") or "")
    boss_id = int(env_map.get("BOSS_TELEGRAM_ID") or 0)
    secret_code = str(env_map.get("SECRET_CODE") or "")

    telegram_settings = TelegramSettings(
        api_id=tg_api_id,
        api_hash=SecretStr(tg_api_hash),
        bot_token=SecretStr(tg_bot_token),
        bot_id=tg_bot_id,
        telegram_secret=SecretStr(tg_secret),
        boss_telegram_id=boss_id,
        secret_code=SecretStr(secret_code),
    )

    # 2. LLM Providers
    llm_yaml = yaml_cfg.get("llm", {})

    priority_raw = env_map.get("LLM_PRIORITY")
    if priority_raw:
        priority = [p.strip().lower() for p in str(priority_raw).split(",") if p.strip()]
    elif "priority" in llm_yaml and isinstance(llm_yaml["priority"], list):
        priority = [str(p).lower() for p in llm_yaml["priority"]]
    else:
        priority = ["openrouter", "groq", "gemini", "cloudflare", "deepseek"]

    timeout = float(env_map.get("LLM_TIMEOUT") or llm_yaml.get("timeout") or 30.0)
    retry = int(env_map.get("LLM_RETRY") or llm_yaml.get("retry") or 2)
    cooldown = float(env_map.get("LLM_COOLDOWN_SECONDS") or llm_yaml.get("cooldown_seconds") or 300.0)

    # OpenRouter
    openrouter_keys = parse_api_keys(
        env_map.get("OPENROUTER_API_KEYS"),
        env_map.get("OPENROUTER_API_KEY"),
    )
    openrouter_model = str(env_map.get("OPENROUTER_MODEL") or "openai/gpt-4o-mini")

    # Groq
    groq_keys = parse_api_keys(
        env_map.get("GROQ_API_KEYS"),
        env_map.get("GROQ_API_KEY"),
    )
    groq_model = str(env_map.get("GROQ_MODEL") or "qwen/qwen3.8-27b")

    # Gemini
    gemini_keys = parse_api_keys(
        env_map.get("GEMINI_API_KEYS"),
        env_map.get("GEMINI_API_KEY"),
    )

    # DeepSeek
    deepseek_keys = parse_api_keys(
        env_map.get("DEEPSEEK_API_KEYS"),
        env_map.get("DEEPSEEK_API_KEY"),
    )

    # OpenAI
    openai_keys = parse_api_keys(
        env_map.get("OPENAI_API_KEYS"),
        env_map.get("OPENAI_API_KEY"),
    )

    # Cloudflare accounts
    cf_accounts_raw = parse_cloudflare_credentials(env_map)
    cf_accounts = [
        CloudflareAccount(account_id=acc["account_id"], api_key=SecretStr(acc["api_key"]))
        for acc in cf_accounts_raw
    ]

    llm_settings = LLMSettings(
        priority=priority,
        timeout=timeout,
        retry=retry,
        cooldown_seconds=cooldown,
        openrouter_api_keys=[SecretStr(k) for k in openrouter_keys],
        openrouter_model=openrouter_model,
        groq_api_keys=[SecretStr(k) for k in groq_keys],
        groq_model=groq_model,
        gemini_api_keys=[SecretStr(k) for k in gemini_keys],
        deepseek_api_keys=[SecretStr(k) for k in deepseek_keys],
        openai_api_keys=[SecretStr(k) for k in openai_keys],
        cloudflare_accounts=cf_accounts,
    )

    # 3. Scheduler
    tz = str(env_map.get("SCHEDULER_TIMEZONE") or "Asia/Dhaka")
    morning_h = int(env_map.get("MORNING_REPORT_HOUR") or 8)
    morning_m = int(env_map.get("MORNING_REPORT_MINUTE") or 0)
    night_h = int(env_map.get("NIGHT_SUMMARY_HOUR") or 22)
    night_m = int(env_map.get("NIGHT_SUMMARY_MINUTE") or 0)
    maint_h = int(env_map.get("MAINTENANCE_HOUR") or 3)
    maint_m = int(env_map.get("MAINTENANCE_MINUTE") or 0)
    log_ret = int(env_map.get("LOG_RETENTION_DAYS") or 30)
    cooldown_ret = int(env_map.get("COOLDOWN_RETENTION_HOURS") or 72)
    history_lim = int(env_map.get("CONVERSATION_HISTORY_LIMIT") or 20)

    scheduler_settings = SchedulerSettings(
        timezone=tz,
        morning_report_hour=morning_h,
        morning_report_minute=morning_m,
        night_summary_hour=night_h,
        night_summary_minute=night_m,
        maintenance_hour=maint_h,
        maintenance_minute=maint_m,
        log_retention_days=log_ret,
        cooldown_retention_hours=cooldown_ret,
        conversation_history_limit=history_lim,
    )

    # 4. Research
    search_provider = str(env_map.get("SEARCH_PROVIDER") or "duckduckgo").lower()
    if search_provider not in ("duckduckgo", "tavily", "serper"):
        search_provider = "duckduckgo"
    tavily_key = str(env_map.get("TAVILY_API_KEY") or "")
    serper_key = str(env_map.get("SERPER_API_KEY") or "")
    cache_ttl = int(env_map.get("RESEARCH_CACHE_TTL_SECONDS") or 3600)
    max_results = int(env_map.get("RESEARCH_MAX_RESULTS") or 5)

    research_settings = ResearchSettings(
        search_provider=search_provider,  # type: ignore[arg-type]
        tavily_api_key=SecretStr(tavily_key),
        serper_api_key=SecretStr(serper_key),
        research_cache_ttl_seconds=cache_ttl,
        research_max_results=max_results,
    )

    # 5. Agent
    agent_max_iter = int(env_map.get("AGENT_MAX_ITERATIONS") or 5)
    agent_timeout = float(env_map.get("AGENT_TIMEOUT_SECONDS") or 90.0)

    agent_settings = AgentSettings(
        max_iterations=agent_max_iter,
        timeout_seconds=agent_timeout,
    )

    return AppSettings(
        telegram=telegram_settings,
        llm=llm_settings,
        scheduler=scheduler_settings,
        research=research_settings,
        agent=agent_settings,
        system=system_settings,
    )


def load_settings(
    env_file: Path | str | None = None,
    config_yaml: Path | str | None = None,
    root_dir: Path | str | None = None,
) -> AppSettings:
    """Load configuration from environment file, OS environment, and optional YAML."""
    global _CACHED_SETTINGS

    root = Path(root_dir) if root_dir else _find_repo_root()

    # Determine .env path
    target_env = Path(env_file) if env_file else (root / ".env")
    env_values: dict[str, Any] = {}
    if target_env.exists():
        env_values.update(dotenv_values(target_env, encoding="utf-8-sig"))

    # OS environment overrides .env file values
    env_values.update(os.environ)

    # Optional YAML file
    yaml_values: dict[str, Any] = {}
    target_yaml = Path(config_yaml) if config_yaml else (root / "config.yaml")
    if target_yaml.exists():
        try:
            import yaml
            with open(target_yaml, "r", encoding="utf-8") as f:
                yaml_values = yaml.safe_load(f) or {}
        except Exception:
            pass

    _CACHED_SETTINGS = build_settings_from_mapping(
        env_map=env_values,
        root_dir=root,
        yaml_config=yaml_values,
    )
    return _CACHED_SETTINGS


def get_settings() -> AppSettings:
    """Retrieve currently cached AppSettings singleton or load from default environment."""
    global _CACHED_SETTINGS
    if _CACHED_SETTINGS is None:
        _CACHED_SETTINGS = load_settings()
    return _CACHED_SETTINGS


def reset_settings() -> None:
    """Reset cached configuration singleton (used in test fixtures)."""
    global _CACHED_SETTINGS
    _CACHED_SETTINGS = None
