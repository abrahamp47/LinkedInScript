"""Run tracking operations -- SQLite CRUD for the runs table.

Implements:
- record_run_start: Insert new run with status='running'
- record_run_complete: Update run with final status and metrics
- get_consecutive_failures: Count consecutive scrape_error runs
- get_last_run_time: Get timestamp of most recent completed run
- check_catchup: Log if last run was >24h ago (D-07)

Status taxonomy (enforced by callers):
    'running' | 'success' | 'zero_results' | 'scrape_error' | 'pipeline_error'
"""

import logging
from datetime import datetime, timedelta, timezone

from src.storage.database import get_connection, init_db

logger = logging.getLogger(__name__)


def record_run_start(run_id: str) -> None:
    """Insert a new run row with started_at=now(UTC) and status='running'.

    Args:
        run_id: Unique identifier for this pipeline execution.
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        init_db(conn)
        conn.execute(
            "INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, 'running')",
            (run_id, now),
        )


def record_run_complete(
    run_id: str,
    *,
    status: str,
    jobs_found: int = 0,
    jobs_notified: int = 0,
) -> None:
    """Update a run row with completion data.

    If the run_id does not exist (edge case), inserts a new row instead of crashing.
    This handles the case where record_run_start was never called (e.g., during testing).

    Args:
        run_id: Unique identifier for this pipeline execution.
        status: Final status ('success', 'zero_results', 'scrape_error', 'pipeline_error').
        jobs_found: Total raw jobs scraped.
        jobs_notified: New jobs sent to user.
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        init_db(conn)
        # Try UPDATE first
        cursor = conn.execute(
            """UPDATE runs
               SET completed_at = ?, status = ?, jobs_found = ?, jobs_notified = ?
               WHERE run_id = ?""",
            (now, status, jobs_found, jobs_notified, run_id),
        )
        # If no row was updated, insert (handles edge case gracefully)
        if cursor.rowcount == 0:
            conn.execute(
                """INSERT INTO runs (run_id, started_at, completed_at, status, jobs_found, jobs_notified)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, now, now, status, jobs_found, jobs_notified),
            )


def get_consecutive_failures() -> int:
    """Count consecutive completed runs with status='scrape_error'.

    Scans runs in reverse chronological order (by completed_at), skipping
    rows with status='running' or status='pipeline_error' (not completed runs).
    Stops counting when hitting 'success' or 'zero_results'.

    Returns:
        Number of consecutive scrape_error runs from most recent backward.
        Returns 0 if no runs exist (first-run edge case).
    """
    with get_connection() as conn:
        init_db(conn)
        rows = conn.execute(
            """SELECT status FROM runs
               WHERE status IN ('success', 'zero_results', 'scrape_error')
               ORDER BY completed_at DESC"""
        ).fetchall()

    count = 0
    for row in rows:
        if row["status"] == "scrape_error":
            count += 1
        else:
            # success or zero_results breaks the streak
            break
    return count


def get_last_run_time() -> str | None:
    """Get the ISO timestamp of the most recent completed run.

    Returns:
        ISO timestamp string, or None if no completed runs exist.
    """
    with get_connection() as conn:
        init_db(conn)
        row = conn.execute(
            """SELECT completed_at FROM runs
               WHERE completed_at IS NOT NULL
               ORDER BY completed_at DESC LIMIT 1"""
        ).fetchone()

    if row is None:
        return None
    return row["completed_at"]


def check_catchup() -> None:
    """Log if last successful/completed run was >24h ago (D-07).

    Handles edge cases:
    - Empty runs table (first run): logs "First run -- no previous history"
    - Last run <24h ago: no log
    - Last run >24h ago: logs catch-up message with hours since last run
    """
    with get_connection() as conn:
        init_db(conn)
        row = conn.execute(
            """SELECT completed_at FROM runs
               WHERE status IN ('success', 'zero_results', 'scrape_error')
               ORDER BY completed_at DESC LIMIT 1"""
        ).fetchone()

    if row is None:
        logger.info("First run -- no previous history")
        return

    last_run = datetime.fromisoformat(row["completed_at"])
    # Ensure timezone-aware comparison
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    hours_since = (now - last_run).total_seconds() / 3600

    if hours_since > 24:
        logger.info("Catch-up run triggered -- last run was %.1fh ago", hours_since)
