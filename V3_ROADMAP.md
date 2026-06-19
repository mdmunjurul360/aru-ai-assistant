# Aru AI V3 - Implementation Roadmap

## ✅ Phase 1: Anti-Spam System (COMPLETED)

### What Was Implemented

**New Module:** `modules/anti_spam.py`
- `AntiSpamManager` class with SQLite persistence
- Tracks user cooldowns (3-hour default)
- Boss exempt from all cooldowns
- Limits to 1 reply per cooldown window
- Ignores users after 100 messages during cooldown
- Detailed activity logging:
  - `AUTO_REPLY_SENT` — when reply sent to unauthorized user
  - `AUTO_REPLY_SKIPPED` — when reply blocked by cooldown
  - `COOLDOWN_ACTIVE` — normal cooldown tracking
  - `SPAM_THRESHOLD_REACHED` — when 100+ messages sent

**New Command:** `/cooldown`
- Shows user cooldown status
- Displays: User ID, Last reply time, Remaining hours, Message count

**Database Changes:**
- New table: `user_cooldowns` (user_id, last_reply_at, message_count, timestamps)

**Main.py Updates:**
- Integrated `AntiSpamManager` into `AruBot`
- Updated `_handle_message()` to check cooldown before replying
- Added `/cooldown` to boss-only command list
- Proper logging for all anti-spam actions

---

## 📋 Phase 2: V3 Architecture Preparation

### Planned Features (NO BREAKING CHANGES TO V2)

#### 1. **Browser Automation**
- Upgrade `modules/browser.py` from stub
- Playwright integration for job search automation
- Screenshot/PDF generation capability

#### 2. **Job Search Agent**
- Autonomous job listing scraper
- Filter by location, salary, keywords
- Send daily/weekly job digest to Boss
- Store job listings in SQLite

#### 3. **Research Agent** (Expand Existing)
- Multi-source fact verification
- Citation tracking
- Generate research reports
- Store research history

#### 4. **File Intelligence**
- Document upload/processing
- PDF text extraction
- File summarization
- Version tracking

#### 5. **Health Monitoring**
- System resource tracking (CPU, memory, disk)
- API health checks (Groq, Telegram, etc.)
- Alerting system
- Performance metrics

---

### Folder Structure (V3)

```
aru-ai/
├── modules/
│   ├── __init__.py
│   ├── anti_spam.py          ✅ NEW
│   ├── ai.py                 (v2 keep)
│   ├── activity_log.py        (v2 keep)
│   ├── auth.py               (v2 keep)
│   ├── browser.py            → UPGRADE
│   ├── commands.py            (v2 keep + /cooldown)
│   ├── config.py             (v2 keep)
│   ├── logging_setup.py       (v2 keep)
│   ├── memory.py             (v2 keep)
│   ├── scheduler.py          (v2 keep)
│   ├── tasks.py              (v2 keep)
│   ├── voice.py              (v2 keep)
│   ├── jobs.py               📝 NEW
│   ├── research_v3.py         📝 PLAN
│   ├── files.py              📝 NEW
│   ├── health.py             📝 NEW
│   └── future.py             (v2 keep)
├── database/
│   ├── memory.db             (v2 schema + user_cooldowns table)
│   └── migrations/           📝 NEW (for schema upgrades)
├── logs/
│   ├── aru.log               (v2 keep)
│   └── health.log            📝 NEW
├── docs/
│   ├── V3_SPEC.md            📝 NEW
│   └── ARCHITECTURE.md        📝 NEW
├── main.py                   (update version to v3)
├── requirements.txt          (add Playwright, new deps)
└── .env.example             (add V3 config options)
```

---

### Database Schema Updates

**No changes to existing tables** (V2 fully preserved)

**New table:** `user_cooldowns` ✅ (already created)

**Planned additions:**
- `job_listings` — Job search results
- `research_reports` — Saved research data
- `file_documents` — File upload metadata
- `health_metrics` — System health tracking

---

### Environment Variables (V3)

Add to `.env.example`:

```bash
# Job Search (optional)
JOB_SEARCH_ENABLED=false
JOB_SEARCH_INTERVAL=86400  # seconds
JOB_KEYWORDS=python,backend,remote

# Browser Automation
BROWSER_TIMEOUT=30
BROWSER_HEADLESS=true

# Research Agent
RESEARCH_SOURCES=wikipedia,arxiv,news
RESEARCH_CACHE_HOURS=24

# File Intelligence
MAX_FILE_SIZE=10485760  # 10MB
ALLOWED_FILETYPES=pdf,txt,docx

# Health Monitoring
HEALTH_CHECK_INTERVAL=300  # seconds
HEALTH_ALERT_THRESHOLD=80  # CPU/Memory %
```

---

### Dependencies (New for V3)

```txt
playwright>=1.40.0           # Browser automation
pypdf>=4.0.0                 # PDF extraction
python-docx>=1.0.0           # Word doc parsing
beautifulsoup4>=4.12.0       # Web scraping
psutil>=5.9.0                # System metrics
feedparser>=6.0.0            # RSS feeds
```

---

### Implementation Roadmap

| Phase | Feature | Status | Est. Lines |
|-------|---------|--------|-----------|
| ✅ Phase 1 | Anti-Spam System | DONE | ~280 |
| 📋 Phase 2.1 | Browser Upgrade | PENDING | ~400 |
| 📋 Phase 2.2 | Job Search Agent | PENDING | ~500 |
| 📋 Phase 2.3 | Research v3 | PENDING | ~300 |
| 📋 Phase 2.4 | File Intelligence | PENDING | ~350 |
| 📋 Phase 2.5 | Health Monitoring | PENDING | ~300 |

**Total new code: ~2,000 lines (keeps V2 intact)**

---

### Critical Design Principles

1. **V2 Stability First**
   - No breaking changes to existing APIs
   - All V2 features work unchanged
   - Backward-compatible database migrations

2. **Modular Architecture**
   - Each feature in separate module
   - Clean imports/exports
   - Independent testing

3. **Async Throughout**
   - Non-blocking operations
   - Proper error handling
   - Timeout management

4. **Persistent Storage**
   - All long-lived data → SQLite
   - Structured activity logging
   - Queryable history

5. **Boss-Only Features**
   - Sensitive operations protected
   - Clear authorization checks
   - Audit trail in activity logs

---

## Next Steps

1. ✅ Verify anti-spam system works
2. Test `/cooldown` command with unauthorized users
3. Upgrade `modules/browser.py` → real Playwright
4. Implement job search agent
5. Expand research capabilities
6. Add file intelligence
7. Deploy health monitoring

Ready to proceed with Phase 2.1? 🚀
