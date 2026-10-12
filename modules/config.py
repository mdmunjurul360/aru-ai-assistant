"""Central configuration loaded from environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

REQUIRED_KEYS = ("TG_API_ID", "TG_API_HASH", "BOSS_TELEGRAM_ID")

# Telegram credentials (supporting TG_* and TELEGRAM_* aliases)
TG_API_ID = 0
TG_API_HASH = ""
TELEGRAM_API_ID = 0
TELEGRAM_API_HASH = ""
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_BOT_ID = 0
TELEGRAM_SECRET = ""

# AI Providers (Multi-Key support with backward compatibility)
OPENROUTER_API_KEYS: list[str] = []
OPENROUTER_API_KEY: str = ""
OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
GROQ_API_KEYS: list[str] = []
GEMINI_API_KEYS: list[str] = []
OPENAI_API_KEYS: list[str] = []
DEEPSEEK_API_KEYS: list[str] = []
CLOUDFLARE_API_KEYS: list[str] = []
GROQ_API_KEY = ""
GEMINI_API_KEY = ""
OPENAI_API_KEY = ""
DEEPSEEK_API_KEY = ""
CLOUDFLARE_API_KEY = ""
CLOUDFLARE_ACCOUNT_ID = ""
CLOUDFLARE_ACCOUNTS: list[dict[str, str]] = []
BOSS_TELEGRAM_ID = 0
SECRET_CODE = ""
GROQ_MODEL = "qwen/qwen3.8-27b"


def parse_api_keys(plural_val: str | None = None, singular_val: str | None = None) -> list[str]:
    """
    Parse and merge API keys from plural and singular env vars.
    Supports comma, semicolon, and newline separation.
    Strips whitespace and quotes, ignores empty tokens, and removes duplicates preserving order.
    """
    import re

    raw_tokens: list[str] = []
    # Process singular first so primary key retains index 1 if both exist
    for source in (singular_val, plural_val):
        if not source:
            continue
        tokens = re.split(r"[,;\n\r]+", str(source))
        for t in tokens:
            cleaned = t.strip().strip("'\"").strip()
            if cleaned:
                raw_tokens.append(cleaned)

    seen: set[str] = set()
    result: list[str] = []
    for k in raw_tokens:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result


def parse_cloudflare_credentials(
    env_source: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """
    Parse paired Cloudflare account credentials from environment.
    Supports:
      - Numbered variables:
          CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_KEY (or CLOUDFLARE_ACCOUNT_ID_1, CLOUDFLARE_API_KEY_1)
          CLOUDFLARE_ACCOUNT_ID_2, CLOUDFLARE_API_KEY_2
          CLOUDFLARE_ACCOUNT_ID_3, CLOUDFLARE_API_KEY_3
          ... (unlimited accounts: _4, _5, etc.)
      - Multi-key lists with single account ID:
          CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_KEYS (comma-separated)
      - Delimited account pairs:
          CLOUDFLARE_ACCOUNTS (e.g. "acc1:key1,acc2:key2")
    Returns a deduplicated, order-preserved list of dicts:
      [{"account_id": "...", "api_key": "..."}, ...]
    """
    import re

    env = env_source if env_source is not None else os.environ

    accounts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_pair(acc: str | None, key: str | None) -> None:
        c_acc = (acc or "").strip().strip("'\"").strip()
        c_key = (key or "").strip().strip("'\"").strip()
        if c_acc and c_key and (c_acc, c_key) not in seen:
            seen.add((c_acc, c_key))
            accounts.append({"account_id": c_acc, "api_key": c_key})

    # 1. Primary account (CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_ACCOUNT_ID_1)
    acc_1 = env.get("CLOUDFLARE_ACCOUNT_ID") or env.get("CLOUDFLARE_ACCOUNT_ID_1") or ""
    key_1 = env.get("CLOUDFLARE_API_KEY") or env.get("CLOUDFLARE_API_KEY_1") or ""
    keys_1_plural = parse_api_keys(env.get("CLOUDFLARE_API_KEYS"), key_1)
    if acc_1:
        if keys_1_plural:
            for k in keys_1_plural:
                add_pair(acc_1, k)
        elif key_1:
            add_pair(acc_1, key_1)

    # 2. Numbered accounts: _2, _3, _4, ... up to any N
    numbered_indices: set[int] = set()
    for k in env.keys():
        m = re.match(r"^CLOUDFLARE_ACCOUNT_ID_(\d+)$", k, re.IGNORECASE)
        if m:
            numbered_indices.add(int(m.group(1)))
        m2 = re.match(r"^CLOUDFLARE_API_KEY_(\d+)$", k, re.IGNORECASE)
        if m2:
            numbered_indices.add(int(m2.group(1)))
        m3 = re.match(r"^CLOUDFLARE_API_KEYS_(\d+)$", k, re.IGNORECASE)
        if m3:
            numbered_indices.add(int(m3.group(1)))

    for idx in sorted(numbered_indices):
        if idx == 1:
            continue
        acc_n = env.get(f"CLOUDFLARE_ACCOUNT_ID_{idx}") or ""
        key_n = env.get(f"CLOUDFLARE_API_KEY_{idx}") or ""
        keys_n_plural = parse_api_keys(env.get(f"CLOUDFLARE_API_KEYS_{idx}"), key_n)
        if acc_n:
            if keys_n_plural:
                for k in keys_n_plural:
                    add_pair(acc_n, k)
            elif key_n:
                add_pair(acc_n, key_n)

    # 3. Delimited CLOUDFLARE_ACCOUNTS (e.g. "acc1:key1,acc2:key2")
    raw_accounts = env.get("CLOUDFLARE_ACCOUNTS") or ""
    if raw_accounts:
        for item in re.split(r"[,;\n\r]+", str(raw_accounts)):
            item = item.strip()
            if ":" in item:
                parts = item.split(":", 1)
                add_pair(parts[0], parts[1])

    return accounts

LLM_PRIORITY = ["openrouter", "groq", "gemini", "cloudflare", "deepseek"]
LLM_TIMEOUT = 30.0
LLM_RETRY = 2
LLM_COOLDOWN_SECONDS = 300.0

SCHEDULER_TIMEZONE = "Asia/Dhaka"
MORNING_REPORT_HOUR = 8
MORNING_REPORT_MINUTE = 0
NIGHT_SUMMARY_HOUR = 22
NIGHT_SUMMARY_MINUTE = 0

MAINTENANCE_HOUR = 3
MAINTENANCE_MINUTE = 0
LOG_RETENTION_DAYS = 30
COOLDOWN_RETENTION_HOURS = 72
CONVERSATION_HISTORY_LIMIT = 20

SEARCH_PROVIDER = "duckduckgo"
TAVILY_API_KEY = ""
SERPER_API_KEY = ""
RESEARCH_CACHE_TTL_SECONDS = 3600
RESEARCH_MAX_RESULTS = 5
AGENT_MAX_ITERATIONS = 5
AGENT_TIMEOUT_SECONDS = 90.0

DATABASE_DIR = ROOT_DIR / "database"
DATABASE_PATH = DATABASE_DIR / "memory.db"
LOGS_DIR = ROOT_DIR / "logs"
LOG_FILE = LOGS_DIR / "aru.log"
SESSIONS_DIR = ROOT_DIR / "sessions"
SESSION_PATH = SESSIONS_DIR / "aru"

UNAUTHORIZED_REPLY = (
    "দুঃখিত স্যার\n\n"
    "আমি Aru AI। আমি শুধুমাত্র আমার বস মঞ্জুরুলের নির্দেশ পালন করি।\n\n"
    "আপনার মেসেজটি গ্রহণ করা হয়েছে। আমার বস বর্তমানে ব্যস্ত আছেন। তিনি সময় পেলে আপনার সাথে যোগাযোগ করবেন।\n\n"
    "আপনার ধৈর্যের জন্য ধন্যবাদ। 💙"
)

SYSTEM_PROMPT = """You are Aru, the personal AI assistant of your Boss.
You are loyal, intelligent, friendly, witty, helpful and professional.
Always answer in the same language used by the Boss (Bangla or English).
Remember Boss preferences and ongoing projects whenever relevant.
Provide practical answers.
Never be rude to the Boss.
Act like a trusted assistant, planner and productivity partner."""

# Fallback models chain
GROQ_MODEL_FALLBACKS = (
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama-3.1-8b-instant",
)


CONFIG_YAML_PATH = ROOT_DIR / "config.yaml"


def reload_settings() -> None:
    """Load or reload .env and refresh module-level settings."""
    global TG_API_ID, TG_API_HASH, GROQ_API_KEY, BOSS_TELEGRAM_ID, SECRET_CODE
    global TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_ID, TELEGRAM_SECRET
    global GROQ_MODEL, SCHEDULER_TIMEZONE
    global OPENROUTER_API_KEY, OPENROUTER_API_KEYS, OPENROUTER_MODEL
    global GEMINI_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, CLOUDFLARE_API_KEY
    global GROQ_API_KEYS, GEMINI_API_KEYS, OPENAI_API_KEYS, DEEPSEEK_API_KEYS, CLOUDFLARE_API_KEYS
    global CLOUDFLARE_ACCOUNT_ID
    global LLM_PRIORITY, LLM_TIMEOUT, LLM_RETRY, LLM_COOLDOWN_SECONDS
    global MORNING_REPORT_HOUR, MORNING_REPORT_MINUTE
    global NIGHT_SUMMARY_HOUR, NIGHT_SUMMARY_MINUTE
    global MAINTENANCE_HOUR, MAINTENANCE_MINUTE
    global LOG_RETENTION_DAYS, COOLDOWN_RETENTION_HOURS, CONVERSATION_HISTORY_LIMIT
    global SEARCH_PROVIDER, TAVILY_API_KEY, SERPER_API_KEY
    global RESEARCH_CACHE_TTL_SECONDS, RESEARCH_MAX_RESULTS
    global AGENT_MAX_ITERATIONS, AGENT_TIMEOUT_SECONDS

    # Load defaults from config.yaml if present
    if CONFIG_YAML_PATH.exists():
        try:
            import yaml
            with open(CONFIG_YAML_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                llm_cfg = cfg.get("llm", {})
                if "priority" in llm_cfg and isinstance(llm_cfg["priority"], list):
                    LLM_PRIORITY = [str(p).lower() for p in llm_cfg["priority"]]
                if "timeout" in llm_cfg:
                    LLM_TIMEOUT = float(llm_cfg["timeout"])
                if "retry" in llm_cfg:
                    LLM_RETRY = int(llm_cfg["retry"])
                if "cooldown_seconds" in llm_cfg:
                    LLM_COOLDOWN_SECONDS = float(llm_cfg["cooldown_seconds"])
        except Exception:
            pass

    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True, encoding="utf-8-sig")
    else:
        load_dotenv(override=True, encoding="utf-8-sig")

    # Telegram credentials supporting both TG_* and TELEGRAM_* naming conventions
    tg_id_raw = os.getenv("TELEGRAM_API_ID") or os.getenv("TG_API_ID") or "0"
    TG_API_ID = int(tg_id_raw) if str(tg_id_raw).isdigit() else 0
    TELEGRAM_API_ID = TG_API_ID

    TG_API_HASH = (os.getenv("TELEGRAM_API_HASH") or os.getenv("TG_API_HASH") or "").strip()
    TELEGRAM_API_HASH = TG_API_HASH

    TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

    boss_id_raw = os.getenv("TELEGRAM_BOT_ID") or os.getenv("BOSS_TELEGRAM_ID") or "0"
    BOSS_TELEGRAM_ID = int(boss_id_raw) if str(boss_id_raw).isdigit() else 0
    TELEGRAM_BOT_ID = BOSS_TELEGRAM_ID

    SECRET_CODE = (os.getenv("TELEGRAM_SECRET") or os.getenv("SECRET_CODE") or "").strip()
    TELEGRAM_SECRET = SECRET_CODE

    # AI Provider API Keys (Hierarchical Multi-Key loading with fallback)
    OPENROUTER_API_KEYS = parse_api_keys(
        os.getenv("OPENROUTER_API_KEYS"),
        os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEYS") or os.getenv("OPENAI_API_KEY"),
    )
    OPENROUTER_API_KEY = OPENROUTER_API_KEYS[0] if OPENROUTER_API_KEYS else ""
    OPENROUTER_MODEL = (os.getenv("OPENROUTER_MODEL") or "openai/gpt-4o-mini").strip()

    # Backward compatibility aliases
    OPENAI_API_KEYS = OPENROUTER_API_KEYS
    OPENAI_API_KEY = OPENROUTER_API_KEY

    GROQ_API_KEYS = parse_api_keys(os.getenv("GROQ_API_KEYS"), os.getenv("GROQ_API_KEY"))
    GEMINI_API_KEYS = parse_api_keys(os.getenv("GEMINI_API_KEYS"), os.getenv("GEMINI_API_KEY"))
    DEEPSEEK_API_KEYS = parse_api_keys(os.getenv("DEEPSEEK_API_KEYS"), os.getenv("DEEPSEEK_API_KEY"))

    # Cloudflare Multi-Account credentials
    CLOUDFLARE_ACCOUNTS = parse_cloudflare_credentials()
    if CLOUDFLARE_ACCOUNTS:
        CLOUDFLARE_API_KEYS = [a["api_key"] for a in CLOUDFLARE_ACCOUNTS]
        CLOUDFLARE_ACCOUNT_ID = CLOUDFLARE_ACCOUNTS[0]["account_id"]
        CLOUDFLARE_API_KEY = CLOUDFLARE_ACCOUNTS[0]["api_key"]
    else:
        CLOUDFLARE_API_KEYS = parse_api_keys(os.getenv("CLOUDFLARE_API_KEYS"), os.getenv("CLOUDFLARE_API_KEY"))
        CLOUDFLARE_API_KEY = CLOUDFLARE_API_KEYS[0] if CLOUDFLARE_API_KEYS else ""
        CLOUDFLARE_ACCOUNT_ID = (os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip()

    GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""
    GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
    DEEPSEEK_API_KEY = DEEPSEEK_API_KEYS[0] if DEEPSEEK_API_KEYS else ""
    GROQ_MODEL = (os.getenv("GROQ_MODEL") or "qwen/qwen3.8-27b").strip()

    if os.getenv("LLM_PRIORITY"):
        LLM_PRIORITY = [p.strip().lower() for p in os.getenv("LLM_PRIORITY", "").split(",") if p.strip()]
    if os.getenv("LLM_TIMEOUT"):
        LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30.0"))
    if os.getenv("LLM_RETRY"):
        LLM_RETRY = int(os.getenv("LLM_RETRY", "2"))
    if os.getenv("LLM_COOLDOWN_SECONDS"):
        LLM_COOLDOWN_SECONDS = float(os.getenv("LLM_COOLDOWN_SECONDS", "300.0"))

    SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Asia/Dhaka")
    MORNING_REPORT_HOUR = int(os.getenv("MORNING_REPORT_HOUR", "8"))
    MORNING_REPORT_MINUTE = int(os.getenv("MORNING_REPORT_MINUTE", "0"))
    NIGHT_SUMMARY_HOUR = int(os.getenv("NIGHT_SUMMARY_HOUR", "22"))
    NIGHT_SUMMARY_MINUTE = int(os.getenv("NIGHT_SUMMARY_MINUTE", "0"))

    MAINTENANCE_HOUR = int(os.getenv("MAINTENANCE_HOUR", "3"))
    MAINTENANCE_MINUTE = int(os.getenv("MAINTENANCE_MINUTE", "0"))
    LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
    COOLDOWN_RETENTION_HOURS = int(os.getenv("COOLDOWN_RETENTION_HOURS", "72"))
    CONVERSATION_HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "20"))

    SEARCH_PROVIDER = (os.getenv("SEARCH_PROVIDER") or "duckduckgo").strip().lower()
    TAVILY_API_KEY = (os.getenv("TAVILY_API_KEY") or "").strip()
    SERPER_API_KEY = (os.getenv("SERPER_API_KEY") or "").strip()
    RESEARCH_CACHE_TTL_SECONDS = int(os.getenv("RESEARCH_CACHE_TTL_SECONDS", "3600"))
    RESEARCH_MAX_RESULTS = int(os.getenv("RESEARCH_MAX_RESULTS", "5"))
    AGENT_MAX_ITERATIONS = int(os.getenv("AGENT_MAX_ITERATIONS", "5"))
    AGENT_TIMEOUT_SECONDS = float(os.getenv("AGENT_TIMEOUT_SECONDS", "90.0"))


def env_file_status() -> dict[str, str]:
    """Inspect .env file keys without exposing secret values."""
    if not ENV_PATH.exists():
        return {"_file": "missing"}
    raw = dotenv_values(ENV_PATH)
    status: dict[str, str] = {"_file": str(ENV_PATH)}
    tracked_keys: list[str] = [
        *REQUIRED_KEYS,
        "SECRET_CODE",
        "TELEGRAM_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_BOT_ID",
        "GEMINI_API_KEY",
        "GEMINI_API_KEYS",
        "GROQ_API_KEYS",
        "OPENROUTER_API_KEY",
        "OPENROUTER_API_KEYS",
        "OPENROUTER_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_API_KEYS",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_KEYS",
        "CLOUDFLARE_API_KEY",
        "CLOUDFLARE_API_KEYS",
        "CLOUDFLARE_ACCOUNT_ID",
        "GROQ_MODEL",
    ]
    # Dynamically track any numbered CLOUDFLARE_* keys in .env
    for k in raw.keys():
        if k.startswith("CLOUDFLARE_") and k not in tracked_keys:
            tracked_keys.append(k)

    for key in tracked_keys:
        val = (raw.get(key) or "").strip()
        if key not in raw:
            status[key] = "missing"
        elif not val:
            status[key] = "empty"
        else:
            status[key] = "ok"
    return status


def validate_config() -> list[str]:
    """Return list of configuration problems."""
    reload_settings()
    problems: list[str] = []

    if not ENV_PATH.exists():
        problems.append(".env file not found — copy .env.example to .env")

    file_status = env_file_status()
    for key in REQUIRED_KEYS:
        # Check alias fallbacks so neither naming convention causes a false failure
        if key == "TG_API_ID" and (file_status.get("TELEGRAM_API_ID") == "ok" or TG_API_ID or TELEGRAM_API_ID):
            continue
        if key == "TG_API_HASH" and (file_status.get("TELEGRAM_API_HASH") == "ok" or TG_API_HASH or TELEGRAM_API_HASH):
            continue
        if key == "BOSS_TELEGRAM_ID" and (file_status.get("TELEGRAM_BOT_ID") == "ok" or BOSS_TELEGRAM_ID or TELEGRAM_BOT_ID):
            continue

        state = file_status.get(key)
        if state == "missing":
            problems.append(f"{key} missing in .env")
        elif state == "empty":
            problems.append(f"{key} is empty in .env (save the file after filling values)")

    if not TG_API_ID and not TELEGRAM_API_ID:
        problems.append("TG_API_ID invalid or zero")
    if not TG_API_HASH and not TELEGRAM_API_HASH:
        problems.append("TG_API_HASH not loaded")
    if not BOSS_TELEGRAM_ID and not TELEGRAM_BOT_ID:
        problems.append("BOSS_TELEGRAM_ID invalid or zero")

    # LLM Provider Validation:
    # A missing API key for one provider (e.g., Groq) must not stop the application
    # if at least one other provider (e.g., Gemini) is properly configured.
    # Providers without keys should be marked as disabled and skipped.
    # The application should only fail startup if no LLM provider has any valid API keys.
    has_any_llm = bool(
        OPENROUTER_API_KEYS
        or OPENROUTER_API_KEY
        or GEMINI_API_KEYS
        or GROQ_API_KEYS
        or DEEPSEEK_API_KEYS
        or OPENAI_API_KEYS
        or CLOUDFLARE_API_KEYS
        or GEMINI_API_KEY
        or GROQ_API_KEY
        or DEEPSEEK_API_KEY
        or OPENAI_API_KEY
        or CLOUDFLARE_API_KEY
    )
    if not has_any_llm:
        problems.append(
            "No LLM provider configured — at least one provider (OpenRouter, Groq, Gemini, Cloudflare, or DeepSeek) must have a valid API key."
        )

    return problems


# Initial load on import
reload_settings()
