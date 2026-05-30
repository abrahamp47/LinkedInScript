"""Location filter for LinkedInScript.

Implements a two-tier location matching algorithm that:
1. Checks for remote keywords (bypass if matched)
2. Uses comma-split city isolation to prevent false positives like 'Bangalore Road, Hubli'

Exports:
    filter_by_location(jobs, location_aliases, remote_keywords) -> tuple[list[Job], list[Job]]
"""

import logging

from src.models import Job

logger = logging.getLogger(__name__)


def filter_by_location(
    jobs: list[Job],
    location_aliases: list[str],
    remote_keywords: list[str],
) -> tuple[list[Job], list[Job]]:
    """Filter jobs by location, keeping only Bangalore/Remote jobs.

    Two-tier algorithm:
      Tier 1 - Remote bypass: if full location string contains any remote keyword, PASS.
      Tier 2 - City isolation via comma-split: split by comma, check each segment
               against the alias set using exact segment match (lowercased).
               Also checks for 'karnataka' segment (D-04 rule).

    None/empty guard: jobs with None or empty location PASS (conservative default).

    Args:
        jobs: List of Job instances to filter.
        location_aliases: List of location alias strings (lowercase).
        remote_keywords: List of remote keyword strings (lowercase).

    Returns:
        Tuple of (passed, rejected) job lists.
    """
    # Build sets for O(1) lookup
    alias_set = set(alias.lower().strip() for alias in location_aliases)
    remote_set = set(kw.lower().strip() for kw in remote_keywords)

    passed: list[Job] = []
    rejected: list[Job] = []

    for job in jobs:
        # None/empty guard: do not reject jobs with missing location data
        if job.location is None or job.location.strip() == "":
            passed.append(job)
            continue

        location_lower = job.location.lower().strip()

        # Tier 1: Remote bypass — check if full location contains any remote keyword
        if _matches_remote(location_lower, remote_set):
            passed.append(job)
            continue

        # Tier 2: City isolation via comma-split
        if _matches_city(location_lower, alias_set):
            passed.append(job)
            continue

        # No match — reject
        rejected.append(job)
        logger.debug(
            "Rejected: %s @ %s -- location mismatch (got: %s)",
            job.title,
            job.company,
            job.location,
        )

    return passed, rejected


def _matches_remote(location_lower: str, remote_set: set[str]) -> bool:
    """Check if the location string contains any remote keyword."""
    for keyword in remote_set:
        if keyword in location_lower:
            return True
    return False


def _matches_city(location_lower: str, alias_set: set[str]) -> bool:
    """Check if any comma-split segment matches a location alias or 'karnataka'.

    Uses exact segment match (segment.strip().lower() in alias_set) to prevent
    false positives like 'Bangalore Road' matching 'bangalore'.

    Per D-04: 'karnataka' alone as a segment means include.
    """
    segments = [seg.strip() for seg in location_lower.split(",")]

    for segment in segments:
        # D-04: Karnataka alone = include
        if segment == "karnataka":
            return True

        # Exact segment match against alias set
        if segment in alias_set:
            return True

    return False
