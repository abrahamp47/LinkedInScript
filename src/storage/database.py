"""SQLite database connection management and schema initialization.

Provides:
    - DB_PATH: Path to the SQLite database file (data/jobs.db)
    - get_connection(): Context manager for database connections with WAL mode
    - init_db(conn): Initialize the database schema (safe to call repeatedly)
    - purge_old_entries(retention_days): Delete entries older than retention_days
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Database path: data/jobs.db relative to project root (per D-07)
# Resolved relative to __file__ for Task Scheduler compatibility (Pitfall 3)
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "jobs.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT DEFAULT '',
    job_url TEXT DEFAULT '',
    description TEXT DEFAULT '',
    date_posted TEXT,
    salary TEXT,
    site TEXT DEFAULT '',
    watchlist_match INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    filter_passed INTEGER DEFAULT 0,
    run_id TEXT NOT NULL,
    is_repost INTEGER DEFAULT 0,
    repost_of_id TEXT,
    notified INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_company_filtered ON jobs(company, filter_passed);
CREATE INDEX IF NOT EXISTS idx_jobs_notified ON jobs(notified);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    jobs_found INTEGER DEFAULT 0,
    jobs_notified INTEGER DEFAULT 0,
    health_alert_sent INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_completed ON runs(completed_at);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
"""


@contextmanager
def get_connection():
    """Get a SQLite connection with WAL mode and row factory.

    Yields a connection that auto-commits on success, rolls back on exception,
    and always closes in finally. WAL mode enables concurrent readers.
    busy_timeout=5000 prevents 'database is locked' at personal scale (Pitfall 6).
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(conn):
    """Initialize database schema. Safe to call on every connection (IF NOT EXISTS).

    Creates the jobs table and all required indices.
    """
    conn.executescript(SCHEMA_SQL)


def purge_old_entries(retention_days: int = 90) -> tuple[int, int]:
    """Delete entries older than retention_days from jobs and runs tables.

    Per D-11: Hard delete (no soft-delete) from both tables.
    Per D-13: Uses first_seen for jobs and started_at for runs.
    Per D-14: Logs purge count only when > 0.

    Args:
        retention_days: Number of days to retain entries (default 90, per D-15).

    Returns:
        Tuple of (jobs_deleted, runs_deleted).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()

    with get_connection() as conn:
        init_db(conn)
        cursor = conn.execute(
            "DELETE FROM jobs WHERE first_seen < ?", (cutoff,)
        )
        jobs_deleted = cursor.rowcount

        cursor = conn.execute(
            "DELETE FROM runs WHERE started_at < ?", (cutoff,)
        )
        runs_deleted = cursor.rowcount

    if jobs_deleted > 0 or runs_deleted > 0:
        logger.info(
            "Purged %d jobs and %d runs older than %d days",
            jobs_deleted,
            runs_deleted,
            retention_days,
        )

    return jobs_deleted, runs_deleted
