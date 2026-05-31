from __future__ import annotations

"""Filter pipeline orchestrator for LinkedInScript.

Runs the filter chain in a fixed order and produces summary statistics.

Pipeline order: Location -> Company -> Watchlist -> Salary.
NOTE: D-11 specifies Location -> Company -> Salary -> Watchlist, but D-09 requires
watchlist bypass of salary filter, so watchlist MUST run before salary.
This is a deliberate correction.

Exports:
    run_filter_pipeline(jobs, config) -> FilterResult
    FilterResult (namedtuple with 'passed' and 'stats' fields)
"""

import logging
from typing import NamedTuple

from src.models import Job
from src.filters.experience import filter_by_experience
from src.filters.location import filter_by_location
from src.filters.company import filter_by_company, apply_watchlist
from src.filters.salary import filter_by_salary

logger = logging.getLogger(__name__)

# Default alias sets (used when config doesn't specify them)
DEFAULT_ALIASES = [
    "bangalore",
    "bengaluru",
    "bengaluru urban",
    "whitefield",
    "electronic city",
    "koramangala",
    "indiranagar",
    "hsr layout",
    "marathahalli",
]

DEFAULT_REMOTE = [
    "remote",
    "work from home",
    "wfh",
    "pan india",
    "anywhere in india",
    "hybrid",
]


class FilterResult(NamedTuple):
    """Result of running the filter pipeline."""

    passed: list[Job]
    stats: dict


def run_filter_pipeline(jobs: list[Job], config: dict) -> FilterResult:
    """Run the complete filter pipeline on a list of jobs.

    Pipeline order: Location -> Company Blocklist -> Watchlist Boost -> Salary.
    NOTE: D-11 specifies Location -> Company -> Salary -> Watchlist, but D-09 requires
    watchlist bypass of salary filter, so watchlist MUST run before salary.
    This is a deliberate correction.

    Args:
        jobs: List of Job instances from the scraper.
        config: Configuration dict with 'filters' and 'companies' sections.

    Returns:
        FilterResult with passed jobs and stats dict containing:
        total_in, total_out, location_rejected, company_rejected, salary_rejected, watchlist_boosted.
    """
    total_in = len(jobs)

    if total_in == 0:
        return FilterResult(
            passed=[],
            stats={
                "total_in": 0,
                "total_out": 0,
                "location_rejected": 0,
                "company_rejected": 0,
                "salary_rejected": 0,
                "watchlist_boosted": 0,
            },
        )

    # Extract config values with defaults
    filters_config = config.get("filters", {})
    companies_config = config.get("companies", {})

    location_aliases = filters_config.get("location_aliases", DEFAULT_ALIASES)
    remote_keywords = filters_config.get("remote_keywords", DEFAULT_REMOTE)
    blocklist = companies_config.get("blocklist", [])
    watchlist = companies_config.get("watchlist", [])

    # Step 0: Experience level filter (reject senior roles)
    experience_passed, experience_rejected = filter_by_experience(jobs)

    # Step 1: Location filter
    location_passed, location_rejected = filter_by_location(
        experience_passed, location_aliases, remote_keywords
    )

    # Step 2: Company blocklist filter
    company_passed, company_rejected = filter_by_company(location_passed, blocklist)

    # Step 3: Watchlist boost (flags matching jobs, does not remove any)
    apply_watchlist(company_passed, watchlist)

    # Step 4: Salary filter (watchlist companies bypass per D-09)
    min_salary = filters_config.get("min_salary_monthly", 30000)
    salary_passed, salary_rejected_list = filter_by_salary(
        company_passed, min_salary, respect_watchlist=True
    )
    final_passed = salary_passed

    # Count watchlist matches
    watchlist_boosted = sum(1 for job in final_passed if job.watchlist_match)

    # Build stats
    salary_rejected = len(salary_rejected_list)
    stats = {
        "total_in": total_in,
        "total_out": len(final_passed),
        "experience_rejected": len(experience_rejected),
        "location_rejected": len(location_rejected),
        "company_rejected": len(company_rejected),
        "salary_rejected": salary_rejected,
        "watchlist_boosted": watchlist_boosted,
    }

    # Log INFO summary
    logger.info(
        "Filtered: %d -> %d (%d experience, %d location, %d company, %d salary, %d watchlist)",
        stats["total_in"],
        stats["total_out"],
        stats["experience_rejected"],
        stats["location_rejected"],
        stats["company_rejected"],
        stats["salary_rejected"],
        stats["watchlist_boosted"],
    )

    return FilterResult(passed=final_passed, stats=stats)
