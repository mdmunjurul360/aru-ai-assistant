"""Central configuration loaded from environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

REQUIRED_KEYS = ("TG_API_ID", "TG_API_HASH", "GROQ_API_KEY", "BOSS_TELEGRAM_ID")

TG_API_ID = 0
TG_API_HASH = ""
GROQ_API_KEY = ""
BOSS_TELEGRAM_ID = 0
SECRET_CODE = ""
GROQ_MODEL = "llama3-70b-8192"

SCHEDULER_TIMEZONE = "Asia/Dhaka"
MORNING_REPORT_HOUR = 8
MORNING_REPORT_MINUTE = 0
NIGHT_SUMMARY_HOUR = 22
NIGHT_SUMMARY_MINUTE = 0

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

# Fallback if primary Groq model is retired
GROQ_MODEL_FALLBACKS = (
    "llama3-70b-8192",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
)


def reload_settings() -> None:
    """Load or reload .env and refresh module-level settings."""
    global TG_API_ID, TG_API_HASH, GROQ_API_KEY, BOSS_TELEGRAM_ID, SECRET_CODE
    global GROQ_MODEL, SCHEDULER_TIMEZONE
    global MORNING_REPORT_HOUR, MORNING_REPORT_MINUTE
    global NIGHT_SUMMARY_HOUR, NIGHT_SUMMARY_MINUTE

    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True, encoding="utf-8-sig")
    else:
        load_dotenv(override=True, encoding="utf-8-sig")

    TG_API_ID = int(os.getenv("TG_API_ID", "0") or "0")
    TG_API_HASH = (os.getenv("TG_API_HASH") or "").strip()
    GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
    BOSS_TELEGRAM_ID = int(os.getenv("BOSS_TELEGRAM_ID", "0") or "0")
    SECRET_CODE = (os.getenv("SECRET_CODE") or "").strip()
    GROQ_MODEL = (os.getenv("GROQ_MODEL") or "llama3-70b-8192").strip()

    SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Asia/Dhaka")
    MORNING_REPORT_HOUR = int(os.getenv("MORNING_REPORT_HOUR", "8"))
    MORNING_REPORT_MINUTE = int(os.getenv("MORNING_REPORT_MINUTE", "0"))
    NIGHT_SUMMARY_HOUR = int(os.getenv("NIGHT_SUMMARY_HOUR", "22"))
    NIGHT_SUMMARY_MINUTE = int(os.getenv("NIGHT_SUMMARY_MINUTE", "0"))


def env_file_status() -> dict[str, str]:
    """Inspect .env file keys without exposing secret values."""
    if not ENV_PATH.exists():
        return {"_file": "missing"}
    raw = dotenv_values(ENV_PATH)
    status: dict[str, str] = {"_file": str(ENV_PATH)}
    for key in REQUIRED_KEYS + ("SECRET_CODE",):
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
        state = file_status.get(key)
        if state == "missing":
            problems.append(f"{key} missing in .env")
        elif state == "empty":
            problems.append(f"{key} is empty in .env (save the file after filling values)")

    if not TG_API_ID:
        problems.append("TG_API_ID invalid or zero")
    if not TG_API_HASH:
        problems.append("TG_API_HASH not loaded")
    if not GROQ_API_KEY:
        problems.append("GROQ_API_KEY not loaded")
    if not BOSS_TELEGRAM_ID:
        problems.append("BOSS_TELEGRAM_ID invalid or zero")

    return problems


# Initial load on import
reload_settings()
