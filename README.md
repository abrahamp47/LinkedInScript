# LinkedInScript

A Windows automation tool that monitors LinkedIn daily for new tech internship openings in Bangalore or remote positions. It filters for quality companies, tracks what you've already seen, and emails you a digest of new listings each day.

## Features

- **Daily LinkedIn monitoring** — Searches across 9 tech intern keywords x 2 locations
- **Smart filtering** — Location (Bangalore/Remote only), company blocklist, salary floor (30k/month), priority watchlist
- **Deduplication** — SQLite-backed tracking with repost detection (same role reposted under new ID)
- **HTML email digest** — Sectioned output (watchlist companies first), with job title, company, link, snippet, location, posted date
- **Unattended scheduling** — Windows Task Scheduler with catch-up logic and health monitoring
- **Resilient operation** — Graceful handling of LinkedIn blocking (partial results), SMTP fallback (saves to HTML file), DB auto-purge (90-day retention)

## Quick Start

### Prerequisites

- Python 3.12+
- Windows 11 (for Task Scheduler automation)
- Gmail account with 2-Step Verification enabled

### Installation

```bash
git clone https://github.com/abrahamp47/LinkedInScript.git
cd LinkedInScript
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### First Run

```bash
python main.py
```

On first run, creates `config.yaml` from the example template. Edit it with your preferences, then run again.

### Configure Email

1. Generate a Gmail App Password (requires 2FA): https://myaccount.google.com/apppasswords
2. Create `.env` in the project root:
   ```
   EMAIL_PASSWORD=your16charpassword
   ```
3. Edit `config.yaml`:
   ```yaml
   email:
     enabled: true
     sender_email: "your.email@gmail.com"
     recipient_email: "your.email@gmail.com"
   ```
4. Verify:
   ```bash
   python main.py --test-email
   ```

### Schedule Daily Runs

```powershell
# Run PowerShell as Administrator
.\scripts\install-task.ps1
```

The tool will run daily at the time specified in `config.yaml` (default 08:00). If your PC was off, it runs at next opportunity.

## Usage

```bash
python main.py              # Fetch jobs, filter, send email digest
python main.py --verbose    # Print full job details to console
python main.py --dry-run    # Preview digest without sending or updating DB
python main.py --test-email # Verify SMTP configuration
python main.py --status     # Show last run, failure count, next scheduled time
python main.py --uninstall  # Remove scheduled task, database, logs, config
```

## Configuration

All settings live in `config.yaml` (created from `config.example.yaml` on first run):

| Section | Key Settings |
|---------|-------------|
| `search.keywords` | List of job search terms |
| `search.locations` | Target locations for search |
| `companies.watchlist` | Priority companies (always included, salary filter waived) |
| `companies.blocklist` | Rejected companies (TCS, Infosys, etc.) |
| `filters.min_salary_monthly` | Minimum salary threshold (default 30000) |
| `email.*` | SMTP settings for digest delivery |
| `schedule.time` | Daily run time in 24h format |
| `database.retention_days` | Auto-purge entries older than N days (default 90) |

## How It Works

```
LinkedIn ──> Scraper ──> Filter Pipeline ──> SQLite Dedup ──> Email Digest
              │              │                    │               │
              │         Location filter      Track seen      HTML template
              │         Company blocklist    Repost detect   Sectioned output
              │         Salary filter        Company group   Plain text alt
              │         Watchlist priority                   SMTP delivery
              │
         python-jobspy
         Rate limiting
         UA rotation
```

1. **Scrape** — Searches LinkedIn via python-jobspy across all keyword/location combinations with rate limiting
2. **Filter** — Applies location, company, salary, and watchlist filters in sequence
3. **Deduplicate** — Checks SQLite for previously seen job IDs, detects reposts via title similarity
4. **Notify** — Renders HTML email digest grouped by company, sends via Gmail SMTP
5. **Track** — Records run status for health monitoring, alerts on consecutive failures

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Some LinkedIn searches blocked | Proceeds with partial results, shows warning in email footer |
| All searches blocked | Logs CRITICAL, skips email, health monitor tracks the failure |
| SMTP send fails | Saves digest to `output/digest-YYYY-MM-DD.html`, jobs re-queued for next run |
| Previous email failed | Next successful email includes a note about saved fallback files |
| 2+ consecutive scrape failures | Sends health alert email |
| PC was off at scheduled time | Runs at next opportunity (StartWhenAvailable) |

## Uninstall

```bash
python main.py --uninstall
```

This removes:
- Windows Task Scheduler task
- SQLite database (`data/`)
- Log files (`logs/`)
- Fallback HTML digests (`output/`)
- User configuration (`config.yaml`, `.env`)

Source code is preserved. To reinstall, run `python main.py` again.

To only remove the scheduled task without touching data:
```powershell
.\scripts\uninstall-task.ps1
```

## Project Structure

```
LinkedInScript/
├── main.py                    # Entry point and pipeline orchestration
├── config.example.yaml        # Template configuration
├── requirements.txt           # Python dependencies
├── docs/
│   └── SETUP.md              # Detailed email and Task Scheduler setup guide
├── scripts/
│   ├── install-task.ps1      # Register Windows Task Scheduler job
│   └── uninstall-task.ps1    # Remove scheduled task
├── src/
│   ├── config.py             # Config loading, validation, logging setup
│   ├── models.py             # Job dataclass
│   ├── scraper/
│   │   └── linkedin.py       # LinkedIn scraping via python-jobspy
│   ├── filters/
│   │   ├── location.py       # Bangalore/Remote location filter
│   │   ├── company.py        # Blocklist and watchlist matching
│   │   ├── salary.py         # Indian salary format parsing
│   │   └── pipeline.py       # Filter orchestration
│   ├── storage/
│   │   ├── database.py       # SQLite schema, connections, purge
│   │   └── dedup.py          # Repost detection, company grouping
│   ├── notifications/
│   │   ├── renderer.py       # Jinja2 HTML + plain text rendering
│   │   ├── sender.py         # SMTP delivery
│   │   └── templates/
│   │       └── digest.html   # Email template
│   └── scheduling/
│       ├── runs.py           # Run tracking and catch-up detection
│       └── health.py         # Consecutive failure monitoring
└── tests/                     # 193 tests (pytest)
```

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Run with verbose output (no email)
python main.py --verbose

# Preview email without sending
python main.py --dry-run
```

## License

MIT
