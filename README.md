# Aru — Personal Telegram AI UserBot

**Aru** is a production-ready Python Telegram UserBot that acts as your personal AI assistant: task manager, memory system, scheduler, and future automation hub.

## Tech Stack

- Python 3.11+
- [Telethon](https://docs.telethon.dev/) — Telegram UserBot
- [Groq API](https://console.groq.com/) — `llama3-70b-8192`
- SQLite — memories & tasks
- APScheduler — morning reports, night summaries, reminders
- Playwright — reserved for future browser automation

## Project Structure

```
aru-ai/
├── .env                 # Your secrets (not committed)
├── .env.example
├── requirements.txt
├── main.py
├── modules/
│   ├── ai.py
│   ├── auth.py
│   ├── memory.py
│   ├── tasks.py
│   ├── scheduler.py
│   ├── browser.py
│   ├── commands.py
│   ├── config.py
│   └── future.py
├── database/
│   └── memory.db        # Created on first run
├── logs/
│   └── aru.log
└── sessions/
    └── aru.session      # Created on first login
```

## Installation

### 1. Prerequisites

- Python 3.11 or newer
- A Telegram account
- Telegram API credentials from [my.telegram.org](https://my.telegram.org/apps)
- Groq API key from [console.groq.com](https://console.groq.com/keys)

### 2. Clone or copy the project

```bash
cd aru-ai
```

### 3. Create a virtual environment (recommended)

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure environment

Copy the example file and fill in your values:

```bash
copy .env.example .env
```

Edit `.env`:

| Variable | Description |
|----------|-------------|
| `TG_API_ID` | Telegram API ID (integer) |
| `TG_API_HASH` | Telegram API hash |
| `GROQ_API_KEY` | Groq API key |
| `BOSS_TELEGRAM_ID` | Your numeric Telegram user ID |
| `SECRET_CODE` | Optional code for `/unlock` |

**Find your Telegram user ID:** message [@userinfobot](https://t.me/userinfobot) or [@getidsbot](https://t.me/getidsbot).

### 5. (Optional) Playwright for future automation

```bash
playwright install chromium
```

Browser automation is stubbed in `modules/browser.py` until you enable it.

## Run

From the `aru-ai` directory:

```bash
python main.py
```

**First run:** Telethon will ask for your phone number and login code in the terminal. If you use 2FA, enter your password when prompted.

**Expected startup output:**

```
=====================
ARU AI ONLINE
Telegram Connected
Groq Connected
Memory Loaded
Boss Verification Active
=====================
```

Logs are written to `logs/aru.log`.

## Usage

### Chat with Aru

Send any private message to your own account (UserBot listens on your logged-in account). Aru replies using Groq and injects relevant memories.

In groups, mention your bot username (e.g. `@YourUsername help me`).

### Security

Only `BOSS_TELEGRAM_ID` can use Aru. Others receive:

> দুঃখিত, আপনি আমার বস নন। আমি শুধু আমার বসের নির্দেশ পালন করি।

### Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/status` | System status |
| `/task add <name>` | Add task |
| `/task list` | List pending tasks |
| `/task done <id>` | Mark task done |
| `/task delete <id>` | Delete task |
| `/memory save cat \| title \| content` | Save memory |
| `/memory search <query>` | Search memories |
| `/memory list [category]` | List memories |
| `/memory update id \| title \| content` | Update memory |
| `/memory delete <id>` | Delete memory |
| `/remind YYYY-MM-DD HH:MM message` | One-shot reminder |
| `/unlock <code>` | Verify secret code (optional) |

**Memory categories:** `goal`, `project`, `preference`, `task`, `fact`, `other`

### Scheduler (automatic)

Configured in `.env`:

- **Morning report** — `MORNING_REPORT_HOUR` / `MORNING_REPORT_MINUTE`
- **Night summary** — `NIGHT_SUMMARY_HOUR` / `NIGHT_SUMMARY_MINUTE`
- **Timezone** — `SCHEDULER_TIMEZONE` (default `Asia/Dhaka`)

## Architecture Notes

| Module | Role |
|--------|------|
| `auth.py` | Boss-only verification |
| `ai.py` | Groq chat with retries |
| `memory.py` | SQLite long-term memory |
| `tasks.py` | Task manager |
| `scheduler.py` | APScheduler jobs |
| `browser.py` | Playwright placeholder |
| `future.py` | Stubs: voice, WhatsApp, Gmail, GitHub, research |

## Troubleshooting

- **Missing .env** — Run will exit with a list of missing variables.
- **Groq errors** — Check API key and model name; retries run automatically.
- **Telegram disconnect** — Telethon `auto_reconnect` is enabled; restart if session is invalid.
- **Session issues** — Delete `sessions/aru.session` and log in again.

## Disclaimer

UserBots use your personal Telegram account. Follow [Telegram ToS](https://telegram.org/tos) and use responsibly. This project is for personal assistant use on your own account.

## License

Private personal use — customize as needed.
