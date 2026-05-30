"""Repost detection for LinkedInScript — fuzzy title matching via SequenceMatcher.

Implements DEDUP-02: detect reposted jobs (same company + similar title with new ID).
Per D-03: compares against ALL historical jobs for the company (no time window, no filter_passed constraint).
Per D-04: matching is scoped to same company only.

Normalization pipeline order (documented per review concern):
    lowercase -> remove years -> strip special chars -> collapse whitespace

Exports:
    normalize_title(title: str) -> str
    is_repost(new_title: str, existing_title: str) -> bool
    detect_reposts(new_jobs: list[Job], run_id: str) -> list[dict]
"""

import logging
import re
from difflib import SequenceMatcher

from src.models import Job
from src.storage.database import get_connection, init_db

logger = logging.getLogger(__name__)

# Repost threshold: ratio >= 0.85 means titles are considered the same posting.
# Chosen empirically: "Backend Developer Intern" vs "Frontend Developer Intern" = 0.816 (safely below).
# "SDE Intern 2025" vs "SDE Intern 2024" = 1.0 after normalization (clear repost).
REPOST_THRESHOLD = 0.85

# Compiled regex for year removal (performance consistency with project patterns)
YEAR_PATTERN = re.compile(r"20\d{2}")

# Compiled regex for special character removal
SPECIAL_CHARS_PATTERN = re.compile(r"[^a-z0-9\s]")


def normalize_title(title: str) -> str:
    """Normalize a job title for fuzzy comparison.

    Normalization order: lowercase -> remove years -> strip special chars -> collapse whitespace.

    Steps:
        1. Lowercase the entire title
        2. Remove year patterns (2000-2099)
        3. Strip all non-alphanumeric, non-space characters
        4. Collapse multiple spaces into single space, strip leading/trailing

    Args:
        title: Raw job title string.

    Returns:
        Normalized title suitable for SequenceMatcher comparison.
    """
    # Step 1: lowercase
    title = title.lower()
    # Step 2: remove years (2000-2099)
    title = YEAR_PATTERN.sub("", title)
    # Step 3: strip special chars (keep lowercase letters, digits, spaces)
    title = SPECIAL_CHARS_PATTERN.sub("", title)
    # Step 4: collapse whitespace
    title = " ".join(title.split())
    return title


def is_repost(new_title: str, existing_title: str) -> bool:
    """Check if two titles are similar enough to be a repost.

    Normalizes both titles, then compares using SequenceMatcher ratio.
    A ratio >= REPOST_THRESHOLD (0.85) indicates the titles refer to the same role.

    Args:
        new_title: Title of the newly scraped job.
        existing_title: Title of a historical job from the same company.

    Returns:
        True if titles are similar enough to be considered a repost.
    """
    norm_new = normalize_title(new_title)
    norm_existing = normalize_title(existing_title)
    ratio = SequenceMatcher(None, norm_new, norm_existing).ratio()
    logger.debug(
        "Repost check: '%s' vs '%s' -> ratio=%.3f (threshold=%.2f)",
        norm_new,
        norm_existing,
        ratio,
        REPOST_THRESHOLD,
    )
    return ratio >= REPOST_THRESHOLD


def detect_reposts(new_jobs: list[Job], run_id: str) -> list[dict]:
    """Check new jobs for reposts against ALL historical jobs for each company.

    For each new job, queries ALL historical titles from the same company
    (per D-03: no time window, no filter_passed constraint). If any historical
    title matches above REPOST_THRESHOLD, the job is marked as a repost.

    Deterministic repost_of_id selection: when multiple matches exist, picks
    the one with the earliest first_seen value (ORDER BY first_seen ASC).

    Updates the DB record with is_repost=1 and repost_of_id for matched jobs.

    Args:
        new_jobs: List of Job instances that are genuinely new.
        run_id: Current run ID (for logging context).

    Returns:
        List of dicts: {"job": Job, "is_repost": bool, "repost_of_id": str|None}
    """
    results = []

    with get_connection() as conn:
        init_db(conn)

        for job in new_jobs:
            # Query ALL historical titles for same company, excluding this job.
            # CRITICAL per D-03: do NOT filter on filter_passed.
            # ORDER BY first_seen ASC for deterministic repost_of_id selection.
            cursor = conn.execute(
                """
                SELECT job_id, title, first_seen FROM jobs
                WHERE company = ? AND job_id != ?
                ORDER BY first_seen ASC
                """,
                (job.company, job.job_id),
            )
            historical = cursor.fetchall()

            # Handle empty DB gracefully: no historical jobs = not a repost
            repost_of_id = None
            if historical:
                for row in historical:
                    if is_repost(job.title, row["title"]):
                        # First match in first_seen ASC order = earliest original
                        repost_of_id = row["job_id"]
                        break

            # Update DB record with repost metadata
            if repost_of_id is not None:
                conn.execute(
                    "UPDATE jobs SET is_repost = 1, repost_of_id = ? WHERE job_id = ?",
                    (repost_of_id, job.job_id),
                )
                logger.debug(
                    "Marked job '%s' as repost of '%s' (company: %s)",
                    job.job_id,
                    repost_of_id,
                    job.company,
                )

            results.append(
                {
                    "job": job,
                    "is_repost": repost_of_id is not None,
                    "repost_of_id": repost_of_id,
                }
            )

    return results
