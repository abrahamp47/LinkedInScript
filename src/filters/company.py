from __future__ import annotations

"""Company filter for LinkedInScript.

Implements blocklist rejection and watchlist flagging using case-insensitive
substring matching (per D-05, D-06).

Exports:
    filter_by_company(jobs, blocklist) -> tuple[list[Job], list[Job]]
    apply_watchlist(jobs, watchlist) -> list[Job]
"""

import logging

from src.models import Job

logger = logging.getLogger(__name__)


def filter_by_company(
    jobs: list[Job],
    blocklist: list[str],
) -> tuple[list[Job], list[Job]]:
    """Filter out jobs from blocked companies.

    Uses case-insensitive substring matching: if any blocklist entry (lowercased)
    is found as a substring of job.company.lower(), the job is rejected.

    None/empty guard: jobs with None or empty company PASS (conservative default).

    Args:
        jobs: List of Job instances to filter.
        blocklist: List of company name strings to block.

    Returns:
        Tuple of (passed, rejected) job lists.
    """
    blocklist_lower = [entry.lower().strip() for entry in blocklist]

    passed: list[Job] = []
    rejected: list[Job] = []

    for job in jobs:
        # None/empty guard: do not reject jobs with missing company data
        if job.company is None or job.company.strip() == "":
            passed.append(job)
            continue

        company_lower = job.company.lower()

        # Substring match: if any blocklist entry is IN the company name, reject
        if any(blocked in company_lower for blocked in blocklist_lower):
            rejected.append(job)
            logger.debug(
                "Rejected: %s @ %s -- blocked company",
                job.title,
                job.company,
            )
        else:
            passed.append(job)

    return passed, rejected


def apply_watchlist(
    jobs: list[Job],
    watchlist: list[str],
) -> list[Job]:
    """Flag jobs from watchlist companies with watchlist_match=True.

    Uses case-insensitive substring matching: if any watchlist entry (lowercased)
    is found as a substring of job.company.lower(), set watchlist_match=True.

    None/empty guard: jobs with None or empty company are skipped
    (watchlist_match stays False).

    Does NOT remove any jobs, only flags them. Returns the same list (mutated in-place).

    Args:
        jobs: List of Job instances to check.
        watchlist: List of priority company name strings.

    Returns:
        The same list of jobs (mutated in-place with watchlist_match flags).
    """
    watchlist_lower = [entry.lower().strip() for entry in watchlist]

    for job in jobs:
        # None/empty guard: skip if company is missing
        if job.company is None or job.company.strip() == "":
            continue

        company_lower = job.company.lower()

        # Substring match: if any watchlist entry is IN the company name, flag it
        if any(watched in company_lower for watched in watchlist_lower):
            job.watchlist_match = True

    return jobs
