# Aru AI V3 Architecture Specification

## Overview

**Goal:** Extend Aru V2 with autonomous agents for job search, research, file intelligence, and health monitoring without breaking existing features.

**Design:** Modular, event-driven, async-first, persistent storage.

---

## Phase 2.1: Browser Automation Upgrade

### Current State (`modules/browser.py`)
- Stub/placeholder only
- Playwright import but not used
- Ready for upgrade

### Implementation Plan

**New Class: `BrowserAutomationV3`**

```python
class BrowserAutomationV3:
    async def launch()          # Start Playwright browser
    async def screenshot(url)   # Take screenshot
    async def extract_text(url) # Get page text
    async def extract_table(url, selector)  # Parse HTML tables
    async def fill_form(url, form_data)     # Auto-fill & submit
    async def wait_element(selector, timeout)  # DOM wait
    async def get_pdf(url)      # Generate PDF
```

### Use Cases
- Job listing page scraping
- Form automation
- PDF generation for reports
- Screenshot comparisons

### Dependencies
```
playwright>=1.40.0
```

### Config (`.env`)
```
BROWSER_TIMEOUT=30
BROWSER_HEADLESS=true
BROWSER_USER_AGENT=Mozilla/5.0...
```

---

## Phase 2.2: Job Search Agent

### Database Table: `job_listings`

```sql
CREATE TABLE job_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    salary_min REAL,
    salary_max REAL,
    keywords TEXT,
    url TEXT,
    source TEXT,  -- linkedin, indeed, remoteok, etc
    posted_at TEXT,
    crawled_at TEXT,
    match_score REAL,  -- 0-100 based on keywords
    saved BOOLEAN DEFAULT 0,
    applied BOOLEAN DEFAULT 0,
    created_at TEXT NOT NULL
);
```

### New Module: `modules/jobs.py`

**Class: `JobSearchAgent`**

```python
class JobSearchAgent:
    async def search_jobs(keywords, location, salary_min)
        → List[JobListing]
    
    async def scrape_source(source_name)  # linkedin, indeed, etc
        → List[JobListing]
    
    async def send_daily_digest(chat_id)
        → Send formatted job list to Boss
    
    async def track_job(job_id)
        → Mark as saved/applied
```

### Job Sources (Planned)
- RemoteOK.com (API)
- We Work Remotely (API)
- LinkedIn (web scrape)
- Indeed (web scrape)
- GitHub Jobs (archive + JSON)

### Scoring Algorithm
```
match_score = 0
for keyword in job_keywords:
    if keyword in title: match_score += 20
    if keyword in description: match_score += 10
if remote: match_score += 15
if salary > target: match_score += 10
```

### Automation
```
Scheduler job: Every 24 hours
├─ Scrape all sources
├─ Calculate match scores
├─ Filter matches (score > 60)
├─ Send digest to Boss
└─ Store in database
```

### Boss Commands
```
/jobs search <keywords> [location] [salary]  → Search now
/jobs today                                   → Today's digest
/jobs saved                                   → Show saved jobs
/jobs apply <job_id>                         → Mark applied
/jobs trending                               → Popular keywords
```

---

## Phase 2.3: Research Agent v3

### Expand `modules/research.py`

**New Methods:**

```python
async def multi_source_research(topic, sources)
    → Fetch from: Wikipedia, Arxiv, News APIs, Google Scholar
    
async def generate_report(topic, include_citations)
    → Save formatted markdown report
    
async def fact_check(claim, sources)
    → Verify against multiple sources
    
async def cite_sources(text)
    → Add citations to text
```

### Database Table: `research_reports`

```sql
CREATE TABLE research_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    sources TEXT,  -- JSON array
    report TEXT,   -- Markdown
    citations TEXT,  -- JSON references
    created_at TEXT,
    updated_at TEXT,
    shared BOOLEAN DEFAULT 0
);
```

### Configuration
```
RESEARCH_SOURCES=wikipedia,arxiv,news,scholar
RESEARCH_CACHE_HOURS=24
RESEARCH_MIN_CONFIDENCE=0.7
```

### Commands
```
/research <topic>              → Quick search (v2 existing)
/research detailed <topic>     → Multi-source report
/research cite <topic>         → With citations
/research history              → Past reports
```

---

## Phase 2.4: File Intelligence

### New Module: `modules/files.py`

**Database Table: `file_documents`**

```sql
CREATE TABLE file_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_hash TEXT UNIQUE,  -- SHA256
    file_size INTEGER,
    filetype TEXT,  -- pdf, txt, docx, etc
    summary TEXT,
    keywords TEXT,
    language TEXT,
    page_count INTEGER,
    content_preview TEXT,  -- First 500 chars
    uploaded_at TEXT,
    version INTEGER DEFAULT 1,
    is_latest BOOLEAN DEFAULT 1
);
```

### Class: `FileIntelligence`

```python
async def upload_file(message, file_data)
    → Store + extract + summarize
    
async def summarize(file_id)
    → Generate markdown summary
    
async def search_documents(query)
    → Full-text search in file_documents
    
async def extract_metadata(file_data, filetype)
    → Author, dates, keywords, language
    
async def version_tracking(file_hash)
    → Detect updates to same file
```

### Supported Types
```
PDF     → pypdf (text extraction)
DOCX    → python-docx
TXT     → Raw text
Images  → OCR (planned: pytesseract)
```

### Boss Commands
```
/upload <attach file>          → Upload + summarize
/files list                     → Show uploaded files
/files search <keyword>         → Full-text search
/files download <file_id>       → Retrieve file
```

---

## Phase 2.5: Health Monitoring

### New Module: `modules/health.py`

**Database Table: `health_metrics`**

```sql
CREATE TABLE health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT,  -- groq, telegram, database, system
    status TEXT,  -- ok, warning, error
    cpu_percent REAL,
    memory_percent REAL,
    memory_mb INTEGER,
    disk_percent REAL,
    response_time_ms REAL,
    error_message TEXT,
    checked_at TEXT,
    created_at TEXT
);
```

### Class: `HealthMonitor`

```python
async def check_system()
    → CPU, memory, disk usage
    
async def check_services()
    → Groq, Telegram, DB, APIs
    
async def health_report()
    → Formatted status report
    
async def alert_if_critical()
    → Send alert if threshold exceeded
```

### Thresholds (configurable)
```
CPU > 80%              → WARNING
Memory > 85%           → WARNING
Disk > 90%             → WARNING
API response > 5s      → WARNING
Service down           → CRITICAL ALERT
```

### Boss Commands
```
/health                        → Quick status
/health detailed               → Full metrics
/health history [hours]        → Past 24h report
/health alerts                 → Show recent alerts
```

### Automatic Alerts
```
Every 5 minutes:
  └─ Check critical services
  └─ If critical issue found:
     └─ Send alert to Boss with details
     └─ Log to activity + health.log
```

---

## Configuration Files

### `.env` additions (V3)

```bash
# ===== JOB SEARCH =====
JOB_SEARCH_ENABLED=false
JOB_SEARCH_INTERVAL=86400
JOB_KEYWORDS=python,backend,fastapi,async
JOB_LOCATION=Remote
JOB_SALARY_MIN=50000
JOB_APPLY_TRACKING=true

# ===== BROWSER AUTOMATION =====
BROWSER_TIMEOUT=30
BROWSER_HEADLESS=true
BROWSER_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36

# ===== RESEARCH =====
RESEARCH_SOURCES=wikipedia,arxiv,news
RESEARCH_CACHE_HOURS=24
RESEARCH_MIN_CONFIDENCE=0.7

# ===== FILE INTELLIGENCE =====
FILES_UPLOAD_DIR=./uploads
MAX_FILE_SIZE=10485760
ALLOWED_FILETYPES=pdf,txt,docx,xlsx

# ===== HEALTH MONITORING =====
HEALTH_CHECK_INTERVAL=300
HEALTH_CPU_THRESHOLD=80
HEALTH_MEMORY_THRESHOLD=85
HEALTH_DISK_THRESHOLD=90
HEALTH_API_TIMEOUT_MS=5000
HEALTH_ALERT_CRITICAL=true
```

---

## Implementation Timeline

| Phase | Feature | Effort | Est. Lines | Timeline |
|-------|---------|--------|-----------|----------|
| ✅ 1 | Anti-Spam | 2h | 280 | DONE |
| 2.1 | Browser → Real | 3h | 400 | Week 1 |
| 2.2 | Job Search | 6h | 500 | Week 1-2 |
| 2.3 | Research v3 | 4h | 300 | Week 2 |
| 2.4 | File Intell | 5h | 350 | Week 2-3 |
| 2.5 | Health Mon | 3h | 300 | Week 3 |

**Total effort: ~23 hours**
**Total new code: ~2,100 lines**
**Zero breaking changes to V2**

---

## Testing Strategy

### Unit Tests
```
tests/
├── test_anti_spam.py       ✅ Ready
├── test_browser.py         → New
├── test_jobs.py           → New
├── test_research_v3.py    → New
├── test_files.py          → New
└── test_health.py         → New
```

### Integration Tests
```
End-to-end flows:
├─ Unauthorized → cooldown → spam threshold
├─ Job search → scrape → digest → send
├─ Upload file → extract → search
├─ Health check → alert → log
```

### Load Testing
```
Anti-spam: 1000 unauthorized users
Job scrape: 10,000 listings/day
Health checks: Every 5 minutes
```

---

## Deployment Checklist

- [ ] Database migrations (if any)
- [ ] Add .env variables
- [ ] Install new dependencies: `pip install -r requirements-v3.txt`
- [ ] Run migrations: `python -m alembic upgrade head`
- [ ] Test anti-spam with dummy users
- [ ] Launch one new phase at a time
- [ ] Monitor logs/activity for 24h
- [ ] Adjust thresholds based on real usage

---

## Future Extensions (V4)

- Telegram bot API for job alerts
- WhatsApp integration
- Gmail automation
- GitHub activity tracking
- Notion sync
- Custom webhook handlers
- Machine learning for job matching

---

**Status:** Architecture complete. Ready for implementation. 🚀
