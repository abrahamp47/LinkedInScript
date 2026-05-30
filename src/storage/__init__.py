"""Storage module for LinkedInScript — SQLite persistence and deduplication.

Public API:
    store_jobs(jobs, *, filter_passed, run_id) -> dict
    get_new_jobs(job_ids) -> list[str]
    mark_as_notified(job_ids) -> int
    generate_run_id() -> str
    detect_reposts(new_jobs, run_id) -> list[dict]
    group_by_company(jobs) -> dict[str, list]

Implements DEDUP-01: track seen job IDs in SQLite, only report genuinely new listings.
Implements DEDUP-02: repost detection via SequenceMatcher (Plan 03-02).
Implements DEDUP-03: company grouping at presentation layer (Plan 03-02).
Per D-11: clean API functions for downstream use (Phase 4 email, Phase 5 scheduling).
"""

import uuid
from datetime import datetime, timezone
from itertools import groupby
from operator import attrgetter

from src.models import Job
from src.storage.database import get_connection, init_db
from src.storage.dedup import detect_reposts


def generate_run_id() -> str:
    """Generate a unique run identifier.

    Returns a 32-character hex string (uuid4().hex format, no dashes).
    """
    return uuid.uuid4().hex


def store_jobs(jobs: list[Job], *, filter_passed: bool = False, run_id: str) -> dict:
    """Store jobs in the database with UPSERT deduplication.

    Crash-safety: UPSERT with filter_passed=MAX is idempotent -- re-running after
    crash produces identical state. The ON CONFLICT clause preserves first_seen while
    updating last_seen and run_id. filter_passed uses MAX so a job that passes filters
    in any run retains that status permanently.

    Args:
        jobs: List of Job dataclass instances to store.
        filter_passed: Whether these jobs passed the filter pipeline.
        run_id: Unique identifier for this execution run.

    Returns:
        dict with keys: total (int), new (int), updated (int)
    """
    now = datetime.now(timezone.utc).isoformat()
    new_count = 0
    updated_count = 0

    with get_connection() as conn:
        init_db(conn)

        for job in jobs:
            # Check if job already exists to distinguish new vs updated
            existing = conn.execute(
                "SELECT job_id FROM jobs WHERE job_id = ? LIMIT 1",
                (job.job_id,),
            ).fetchone()

            # UPSERT: Insert new job or update existing (parameterized queries only - T-03-01)
            conn.execute(
                """
                INSERT INTO jobs (job_id, title, company, location, job_url,
                                  description, date_posted, salary, site,
                                  watchlist_match, first_seen, last_seen,
                                  filter_passed, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    run_id = excluded.run_id,
                    filter_passed = MAX(jobs.filter_passed, excluded.filter_passed)
                """,
                (
                    job.job_id,
                    job.title,
                    job.company,
                    job.location or "",
                    job.job_url or "",
                    job.description or "",
                    job.date_posted,
                    job.salary,
                    job.site or "",
                    int(job.watchlist_match),
                    now,
                    now,
                    int(filter_passed),
                    run_id,
                ),
            )

            if existing is None:
                new_count += 1
            else:
                updated_count += 1

    return {"total": len(jobs), "new": new_count, "updated": updated_count}


def get_new_jobs(job_ids: list[str]) -> list[str]:
    """Return job_ids from the input that have NOT been previously notified.

    A job is 'new' if:
    - It has never been stored before (not in DB), OR
    - It was stored but never notified (notified=0)

    Per Pitfall 4: a job is new if not previously notified. This ensures retroactive
    filter changes correctly surface previously-stored-but-unnotified jobs.

    Args:
        job_ids: List of job IDs to check (from current run's filtered results).

    Returns:
        List of job_ids that are new (not yet notified to user).
    """
    if not job_ids:
        return []

    with get_connection() as conn:
        init_db(conn)

        # Find which of the provided IDs have already been notified
        placeholders = ",".join("?" * len(job_ids))
        cursor = conn.execute(
            f"SELECT job_id FROM jobs WHERE job_id IN ({placeholders}) AND notified = 1",
            job_ids,
        )
        already_notified = {row["job_id"] for row in cursor.fetchall()}

    return [jid for jid in job_ids if jid not in already_notified]


def mark_as_notified(job_ids: list[str]) -> int:
    """Mark jobs as notified (user has been shown these jobs).

    Called AFTER repost detection and output are complete (Plan 03-02 pipeline order).
    Pipeline order: store_jobs -> get_new_jobs -> detect_reposts -> group_by_company -> output -> mark_as_notified

    Args:
        job_ids: List of job IDs to mark as notified.

    Returns:
        Count of rows updated.
    """
    if not job_ids:
        return 0

    with get_connection() as conn:
        init_db(conn)

        placeholders = ",".join("?" * len(job_ids))
        cursor = conn.execute(
            f"UPDATE jobs SET notified = 1 WHERE job_id IN ({placeholders})",
            job_ids,
        )
        return cursor.rowcount


def group_by_company(jobs: list) -> dict[str, list]:
    """Group jobs by company name for presentation-layer display.

    Per D-05: format chosen for both console output and downstream email digest (Phase 4).
    Per D-06: grouping at presentation layer, not storage layer.

    Returns a dict ordered by count descending (most listings first).
    This is a data structure, not formatted text — usable by both console and email.

    Args:
        jobs: List of Job instances to group.

    Returns:
        dict[str, list]: {company_name: [jobs...]} ordered by count descending.
        Empty dict if input is empty.
    """
    if not jobs:
        return {}

    sorted_jobs = sorted(jobs, key=attrgetter("company"))
    groups = {}
    for company, company_jobs in groupby(sorted_jobs, key=attrgetter("company")):
        groups[company] = list(company_jobs)
    # Sort by count descending (most listings first)
    return dict(sorted(groups.items(), key=lambda x: len(x[1]), reverse=True))
