# Aru — Personal Telegram AI UserBot

**Aru** is a production-ready Python Telegram UserBot that acts as your personal AI assistant: task manager, memory system, scheduler, and future automation hub.

## Tech Stack

- Python 3.11+ (Python 3.12 verified)
- [Telethon](https://docs.telethon.dev/) — Telegram UserBot
- [Groq API](https://console.groq.com/) — `qwen/qwen3.8-27b` / `llama-3.3-70b-versatile` & `whisper-large-v3`
- [Playwright](https://playwright.dev/) — Headless Chromium browser automation & DOM extraction
- Personal AI Operating System — Semantic Memory, Knowledge Base, Autonomous Learning, Multi-Channel, Scheduling, Vision, Voice, Plugins, Observability
- Multi-Agent Autonomous Automation — `AgentManager`, `PlannerAgent`, `AgentEventBus`, DAG decomposition, 6 autonomous workflows
- SQLite (WAL mode) — Centralized transactional store for memories, tasks, logs, cooldowns, cache, vectors, telemetry
- Model Context Protocol (MCP) — Unified Tool Registry, typed schemas, and permission management
- APScheduler — Morning reports, night summaries, reminders, maintenance
- HTTPX — Asynchronous HTTP client for research validation and web requests
- Pytest — Automated unit and integration test suite (146 tests)

## Project Structure

```
aru-ai/
├── .env                 # Your secrets (not committed)
├── .env.example         # Environment template
├── Dockerfile           # Production container build
├── docker-compose.yml   # Multi-service container orchestration
├── config.yaml          # Multi-provider LLM failover configuration
├── config.prod.yaml     # Hardened production configuration
├── requirements.txt     # Python dependencies
├── main.py              # Main Telegram UserBot orchestrator
├── deployment/          # Production deployment configs
│   └── config.prod.yaml # Hardened production configuration
├── .github/workflows/   # CI/CD pipelines
│   └── ci.yml           # Automated lint, test & docker build
├── scripts/             # Operational and health scripts
│   ├── startup_check.py # End-to-end non-interactive readiness check
│   ├── healthcheck.py   # Container runtime healthcheck probe
│   └── backup_restore.py# Zero-downtime hot backup & restore verification
├── modules/
│   ├── llm/             # Multi-Provider Failover (OpenRouter, Groq, Gemini, Cloudflare, DeepSeek)
│   │   ├── provider_manager.py # Orchestrator, failover loop, circuit breaker
│   │   ├── base_provider.py    # BaseLLMProvider abstract interface & health models
│   │   ├── openrouter_provider.py # OpenRouter API adapter (primary)
│   │   ├── gemini_provider.py  # Google Gemini API adapter
│   │   ├── groq_provider.py    # Groq LPU API adapter
│   │   ├── cloudflare_provider.py # Cloudflare Workers AI adapter
│   │   ├── deepseek_provider.py# DeepSeek API adapter
│   │   └── exceptions.py       # Custom provider & circuit breaker exceptions
│   ├── semantic_memory/ # Dense vector embeddings, hybrid search (BM25 + RRF), context compression
│   ├── knowledge_base/  # PDF/DOCX/MD/TXT extractors, semantic chunking, citation engine
│   ├── learning/        # Preference profile learning, pattern mining, proactive automations
│   ├── channels/        # WhatsApp, Gmail, Discord, Telegram, REST API, Webhooks
│   ├── scheduling/      # Habit tracking (streaks), goal tracking (progress %), scheduling intelligence
│   ├── vision/          # OCR, UI component detection, screenshot analysis, Groq Vision
│   ├── voice_system/    # Whisper speech-to-text, wave audio synthesis, conversational turn loop
│   ├── plugins/         # manifest.json, sandbox permission checks, auto-discovery
│   ├── observability/   # Telemetry, token/cost tracking, tool analytics, markdown dashboard
│   ├── multi_agent/     # Multi-Agent Autonomous Automation (6 agents, 6 workflows)
│   ├── tools/           # MCP Tool Registry (Browser, File, Research, Memory, Tasks)
│   ├── research_service.py # Grounded research engine (DuckDuckGo, Tavily, Serper)
│   ├── memory_service.py# Hybrid semantic memory service
│   └── ...
├── tests/               # Automated test suite (pytest: 161 tests)
│   ├── test_provider_manager.py # Multi-provider failover, retry & circuit breaker tests
│   ├── test_sprint7_os.py # Comprehensive Sprint 7 AI Operating System test suite
│   ├── test_multi_agent.py # Sprint 6 multi-agent tests
│   └── ...
├── database/
│   └── memory.db        # SQLite database in WAL mode with FTS5 and research cache
├── logs/
│   └── aru.log          # Rotating application logs
└── sessions/
    └── aru.session      # Telethon session file
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
playwright install chromium
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment

Copy the example file and fill in your values:

```bash
copy .env.example .env
```

Edit `.env`:

| Variable | Description | Required / Optional |
|---|---|---|
| `TG_API_ID` / `TELEGRAM_API_ID` | Telegram API ID from [my.telegram.org](https://my.telegram.org/apps) | Required |
| `TG_API_HASH` / `TELEGRAM_API_HASH` | Telegram API Hash | Required |
| `TELEGRAM_BOT_TOKEN` | Optional Telegram Bot Token | Optional |
| `BOSS_TELEGRAM_ID` / `TELEGRAM_BOT_ID` | Your numeric Telegram user ID (only this user commands Aru) | Required |
| `SECRET_CODE` / `TELEGRAM_SECRET` | Optional unlock code for `/unlock` | Optional |
| `OPENROUTER_API_KEY` / `OPENROUTER_API_KEYS` | OpenRouter API key(s) ([OpenRouter](https://openrouter.ai/)) | Optional / Default Primary |
| `GROQ_API_KEY` / `GROQ_API_KEYS` | Groq API key(s) ([Groq Console](https://console.groq.com/)) | Optional / High-Speed LPU |
| `GEMINI_API_KEY` / `GEMINI_API_KEYS` | Google Gemini API key(s) ([Google AI Studio](https://aistudio.google.com/)) | Optional / Multimodal Fallback |
| `CLOUDFLARE_API_KEY` / `CLOUDFLARE_ACCOUNT_ID` | Cloudflare Workers AI credentials | Optional / Multi-Account Fallback |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_API_KEYS` | DeepSeek API key(s) ([DeepSeek Platform](https://platform.deepseek.com/)) | Optional / Reasoning Fallback |
| `OPENROUTER_MODEL` | OpenRouter model name (default: `openai/gpt-4o-mini`) | Optional |
| `GROQ_MODEL` | Groq model name (default: `qwen/qwen3.8-27b`) | Optional |
| `LLM_PRIORITY` | Comma-separated provider priority (`openrouter,groq,gemini,cloudflare,deepseek`) | Optional |
| `LLM_TIMEOUT` | Provider request timeout in seconds (default: `30`) | Optional |
| `LLM_RETRY` | Number of attempts per provider before failover (default: `2`) | Optional |
| `LLM_COOLDOWN_SECONDS` | Circuit breaker cooldown period in seconds (default: `300`) | Optional |

> **Note:** At least one AI Provider API key (`OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `CLOUDFLARE_API_KEY`, or `DEEPSEEK_API_KEY`) must be configured. Providers will automatically fail over if one experiences downtime or rate limits.

**Find your Telegram user ID:** message [@userinfobot](https://t.me/userinfobot) or [@getidsbot](https://t.me/getidsbot).

## Run

From the `aru-ai` directory:

```bash
python main.py
```

**First run:** Telethon will ask for your phone number and login code in the terminal. If you use 2FA, enter your password when prompted.

**Expected startup output:**

```
=====================
ARU AI v2 ONLINE
Telegram Connected
Groq Connected
Memory Loaded
Boss Verification Active
Tool Registry Active (5 tools)
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

### Feature Status (Sprint 6 — Multi-Agent Autonomous Automation)

| Feature | Status | Description |
|---|:---:|---|
| **Multiple AI Providers** | ✅ Complete | Automatic failover (OpenRouter -> Groq -> Gemini -> Cloudflare -> DeepSeek), retries, exponential backoff, circuit breaker, health monitoring |
| **Multi-Agent Coordination** | ✅ Complete | `AgentManager` coordinating `PlannerAgent` & 5 specialized agents over `AgentEventBus` |
| **Planner Agent** | ✅ Complete | Decomposes complex goals into DAG subtasks, token interpolation (`{{step.result}}`), final synthesis |
| **Specialized Agents** | ✅ Complete | Dedicated agents: `ResearchAgent`, `MemoryAgent`, `BrowserAgent`, `TaskAgent`, `SchedulerAgent` |
| **Autonomous Workflows** | ✅ Complete | 6 Background workflows: Morning briefing, Research updates, Job monitoring, Reminders, Task follow-up, Memory consolidation |
| **Agent Event Bus** | ✅ Complete | Async pub/sub, point-to-point RPC, execution tracing, retries, timeout handling, cooperative cancellation |
| **Telegram Integration** | ✅ Complete | Telethon userbot handling DMs, Saved Messages, mentions |
| **AI Conversation** | ✅ Complete | Unified multi-provider chat with memory and history injection |
| **Persistent History** | ✅ Complete | SQLite `conversation_history` table; survives restarts |
| **FTS5 Memory Search** | ✅ Complete | Virtual table `memories_fts`, sync triggers, BM25 rank ordering |
| **Memory Architecture**| ✅ Complete | Categorized: Conversation, Facts, Preferences, Goals, Projects |
| **Maintenance Scheduler**| ✅ Complete | Nightly jobs: log cleanup, cooldown pruning, cache pruning, WAL checkpoint, VACUUM, ANALYZE |
| **Memory Service Layer**| ✅ Complete | `MemoryService` abstraction isolating business logic for future Vector DB/RAG |
| **Multi-Agent Architecture** | ✅ Complete | 6 specialized agents (Planner, Research, Memory, Browser, Task, Scheduler), AgentEventBus, 6 autonomous workflows |
| **Research Engine** | ✅ Complete | Real web search (DuckDuckGo/Tavily/Serper), deduplication, ranking, citation verification, link validation, persistent caching |
| **Autonomous ReAct Agent** | ✅ Complete | Planner -> Tool -> Observe -> Reason loop, loop prevention, graceful error recovery |
| **Tool Registry & MCP** | ✅ Complete | Model Context Protocol architecture, typed JSON schemas, discovery, permissions |
| **Semantic Memory** | ✅ Complete | Dense vector embeddings, Hybrid Search (FTS5 BM25 + Vector RRF ranking), context compression |
| **Knowledge Base** | ✅ Complete | Multi-format ingestion (PDF, DOCX, Markdown, Text), semantic chunking, citation tracking |
| **Autonomous Learning** | ✅ Complete | User preference profile learning, behavior pattern mining, proactive automation suggestions |
| **Multi-Channel Hub** | ✅ Complete | WhatsApp, Gmail, Discord, Telegram, REST API, Webhooks adapters & ChannelManager |
| **Scheduling Intelligence**| ✅ Complete | Habit tracking (streaks), Goal tracking (progress %), Daily briefing, Weekly review, commitment detector |
| **Vision & UI Understanding**| ✅ Complete | OCR extraction, screenshot understanding, UI element detection, Groq Vision API |
| **Voice Conversations** | ✅ Complete | Whisper Speech-to-Text, pure-Python wave Text-to-Speech synthesis, conversational turn loop |
| **Plugin System** | ✅ Complete | `manifest.json`, granular permissions, sandboxed execution, auto-discovery |
| **Observability & Metrics** | ✅ Complete | Token usage, cost estimation, tool execution analytics, Markdown dashboard |
| **Production Deployment** | ✅ Complete | Docker, Docker Compose, CI/CD GitHub Actions, container healthcheck, backup/restore |
| **Browser Tool** | ✅ Complete | Headless Chromium automation via Playwright (navigation, text extraction, screenshots) |
| **File Reader Tool** | ✅ Complete | Sandboxed workspace file reader with path traversal & secret exclusion |
| **Research Tool** | ✅ Complete | Exposes Grounded Research Engine through standard tool interface |
| **Memory Tool** | ✅ Complete | Exposes SQLite FTS5 persistent memory through standard tool interface |
| **Task Tool** | ✅ Complete | Exposes smart task management through standard tool interface |
| **Task Management** | ✅ Complete | Priority (`urgent`/`high`/`medium`/`low`), status, indexing |
| **Scheduler** | ✅ Complete | Morning reports, night summaries, maintenance, `/remind` cron |
| **Anti-Spam Protection**| ✅ Complete | 3-hour cooldown, 100-msg spam drop, Boss exemption |
| **Database Engine** | ✅ Complete | Centralized SQLite connection manager with WAL mode |
| **Automated Tests** | ✅ Complete | 161 pytest unit & integration tests (100% passing) |

## Multiple AI Providers (Automatic Failover)

Aru includes a resilient, unified Multi-Provider LLM Failover System implemented in [`modules/llm/`](file:///d:/Botbari/aru-ai/modules/llm). When an active provider experiences a network timeout, rate limit (HTTP 429), or service degradation, requests fail over automatically to the next configured provider in the priority chain.

### Failover Architecture

```
1. OpenRouter (Default Primary)
   ↓ (Rate Limit / Quota / Timeout)
2. Groq (Ultra-Fast LPU Inference)
   ↓ (Rate Limit / Outage)
3. Gemini (Google Multimodal & Reasoning)
   ↓ (Rate Limit / Quota)
4. Cloudflare (Cloudflare Workers AI Multi-Account)
   ↓ (Quota / Outage)
5. DeepSeek (Deep Reasoning Fallback)
   ↓ (All Outages Exhausted)
Graceful Fallback Reply ("দুঃখিত বস, AI সিস্টেম এখন...")
```

### Configuration (`config.yaml`)

Configure priority order, timeouts, retries, and circuit breaker cooldown:

```yaml
llm:
  priority:
    - openrouter
    - groq
    - gemini
    - cloudflare
    - deepseek
  timeout: 30
  retry: 2
  cooldown_seconds: 300
```

### Environment Variables

Providers are automatically enabled when their API key is present:

| Provider | Environment Variable | Default Model | Supported Capabilities |
|---|---|---|---|
| **OpenRouter** | `OPENROUTER_API_KEY` / `OPENROUTER_API_KEYS` | `openai/gpt-4o-mini` | Text, Chat, Vision, MCP Tool Calling, Fallbacks |
| **Groq** | `GROQ_API_KEY` / `GROQ_API_KEYS` | `qwen/qwen3.8-27b` | Ultra-fast LPU, Internal model fallbacks, Vision |
| **Gemini** | `GEMINI_API_KEY` / `GEMINI_API_KEYS` | `gemini-2.5-flash` | Text, Chat, Vision, Embeddings |
| **Cloudflare** | `CLOUDFLARE_API_KEY` / `CLOUDFLARE_ACCOUNT_ID` | `@cf/meta/llama-3.3-70b-instruct` | Serverless AI, Multi-Account key pooling |
| **DeepSeek** | `DEEPSEEK_API_KEY` / `DEEPSEEK_API_KEYS` | `deepseek-flash` | Deep reasoning, Code, Multimodal, REST API |

### Circuit Breaker & Health Monitoring

- **Automatic Retries:** Failed calls retry up to `retry` times with exponential backoff (`1.0s`, `2.0s`, ...).
- **Circuit Breaker Cooldown:** When a provider exhausts retries, its circuit breaker opens for `cooldown_seconds` (default 300s). Subsequent requests bypass it immediately to eliminate latency overhead.
- **Self-Healing Recovery:** When the cooldown window elapses, the manager probes the provider with a half-open request; on success, it resets back to `Healthy`.
- **Health Status (`/status`):** Real-time status for each provider is displayed directly in `/status`:

```
📊 Aru AI v2 Status

Telegram: ✅
Groq AI: ✅
Voice: ✅
Memories: 12
Pending tasks: 3

**AI Providers:**
OpenRouter: Healthy (2 keys)
Groq: Healthy (2 keys)
Gemini: Healthy (2 keys)
Cloudflare: Healthy (2 accounts)
DeepSeek: Healthy (1 key)

Time: 2026-10-12 15:00:00
```

### Commands

| Command | Description |
|---|---|
| `/plan <goal>` | Multi-Agent planner decomposes complex goal into DAG subtasks & coordinates execution |
| `/workflow <name>` | Execute autonomous workflow (`morning_briefing`, `job_monitoring`, `research_update`, etc.) |
| `/workflows` | List all registered autonomous background workflows |
| `/agent [--trace\|--plan] <prompt>` | Autonomous ReAct agent or Multi-Agent goal delegation |
| `/help` | Show command reference |
| `/status` | System health, active tools, specialized agents, workflows, and resource metrics |
| `/tools` / `/tools list` | List all registered MCP tools and their permissions |
| `/tool <name>` | Inspect tool schema, description, and required parameters |
| `/tool <name> <json_args>` | Safely execute a registered tool with parameters |
| `/cooldown` | Check user anti-spam cooldown status |
| `/remember <fact>` | Quick-save memory item (auto-indexed for hybrid semantic search) |
| `/memories [category]` | List stored memories |
| `/searchmemory <query>` | Search memories with hybrid FTS5 BM25 + Vector RRF ranking |
| `/forget <id>` | Delete memory item |
| `/clearchat` / `/clearhistory` | Clear persistent chat history for current chat |
| `/memory save/list/search/update/delete` | Full memory management |
| `/task add <title> [\| desc] [\| priority]` | Add smart task |
| `/task list` | List pending tasks ordered by priority |
| `/task status <id> <status>` | Update status (`pending`, `in_progress`, `done`, `cancelled`) |
| `/task priority <id> <priority>` | Update priority (`low`, `medium`, `high`, `urgent`) |
| `/task done <id>` | Mark task completed |
| `/task delete <id>` | Delete task |
| `/research [--refresh] <topic>` | Grounded web research report with verified sources & citations |
| `/remind YYYY-MM-DD HH:MM message` | Schedule one-shot reminder |
| `/unlock <code>` | Verify secret setup code |

### Running Automated Tests

```bash
python -m pytest -v
```

All 161 automated tests run in isolation using temporary SQLite databases.

### Scheduler (automatic)

Configured in `.env`:

- **Morning report** — `MORNING_REPORT_HOUR` / `MORNING_REPORT_MINUTE`
- **Night summary** — `NIGHT_SUMMARY_HOUR` / `NIGHT_SUMMARY_MINUTE`
- **Timezone** — `SCHEDULER_TIMEZONE` (default `Asia/Dhaka`)

## Troubleshooting

- **Missing .env** — Run will exit with a list of missing variables.
- **Groq errors** — Check API key and model name; retries run automatically.
- **Telegram disconnect** — Telethon `auto_reconnect` is enabled; restart if session is invalid.
- **Session issues** — Delete `sessions/aru.session` and log in again.

## Disclaimer

UserBots use your personal Telegram account. Follow [Telegram ToS](https://telegram.org/tos) and use responsibly. This project is for personal assistant use on your own account.

## License

Private personal use — customize as needed.
