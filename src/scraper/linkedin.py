from __future__ import annotations

"""LinkedIn job scraper using python-jobspy with resilient UA rotation and safe column mapping.

Exports:
    ScrapeResult — dataclass with jobs, warnings, total_combos, blocked_combos
    scrape_all_keywords(keywords, locations, results_per_keyword, hours_old, min_delay, max_delay) -> ScrapeResult
"""

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from fake_useragent import UserAgent
from jobspy import scrape_jobs
import jobspy.linkedin as _linkedin_scraper

from src.models import Job
from src.scraper.auth import get_valid_li_at

# Monkey-patch LinkedIn scraper for two improvements:
# 1. Inject f_E=1,2 (Internship + Entry Level) experience filter
# 2. Use authenticated endpoint with li_at cookie when available
#
# LinkedIn's guest API (/jobs-guest/) ignores f_E. The authenticated API
# (/jobs/search/) respects it fully, giving much cleaner intern-only results.

_original_linkedin_scrape = _linkedin_scraper.LinkedIn.scrape
_cached_li_at: str | None = None


def _patched_linkedin_scrape(self, scraper_input, *args, **kwargs):
    """Wrap LinkedIn scraper to inject auth + experience level filter."""
    global _cached_li_at
    original_get = self.session.get

    if _cached_li_at is None:
        _cached_li_at = get_valid_li_at()
    li_at = _cached_li_at

    if li_at:
        # Authenticated mode: set li_at cookie and switch to authenticated endpoint
        self.session.cookies.set("li_at", li_at, domain=".linkedin.com")
        self.session.headers["csrf-token"] = "ajax:0"

    def _get_with_filters(url, *a, **kw):
        if "params" in kw and isinstance(kw["params"], dict):
            kw["params"]["f_E"] = "1,2"
        elif "?" in url and "f_E" not in url:
            url += "&f_E=1%2C2"

        # Switch from guest to authenticated endpoint when cookie present
        if li_at and "/jobs-guest/" in url:
            url = url.replace("/jobs-guest/jobs/api/seeMoreJobPostings/search",
                              "/jobs/search")

        return original_get(url, *a, **kw)

    self.session.get = _get_with_filters
    try:
        return _original_linkedin_scrape(self, scraper_input, *args, **kwargs)
    finally:
        self.session.get = original_get


_linkedin_scraper.LinkedIn.scrape = _patched_linkedin_scrape

logger = logging.getLogger(__name__)

# Static fallback user agents for when fake-useragent fails (network issues, etc.)
STATIC_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

# Mapping from Job dataclass fields to expected python-jobspy DataFrame columns
EXPECTED_COLUMNS = {
    "job_id": "id",
    "title": "title",
    "company": "company",
    "location": "location",
    "job_url": "job_url",
    "description": "description",
    "date_posted": "date_posted",
    "salary": "min_amount",
    "site": "site",
}


@dataclass
class ScrapeResult:
    """Result from scrape_all_keywords with partial-failure tracking.

    Attributes:
        jobs: Deduplicated list of Job instances from successful combos.
        warnings: List of warning strings for blocked combos.
            Format: "Blocked: '{keyword}' in '{location}' -- {ExcType}: {message}"
        total_combos: Total number of keyword x location combinations attempted.
        blocked_combos: Number of combos that raised an exception (detected as blocking).
    """

    jobs: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    total_combos: int = 0
    blocked_combos: int = 0


def _create_user_agent() -> Optional[UserAgent]:
    """Create a UserAgent instance with resilient fallback.

    Returns:
        UserAgent instance if successful, None if fake-useragent is unavailable.
        When None is returned, callers should use STATIC_USER_AGENTS instead.
    """
    try:
        ua = UserAgent(
            fallback="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        return ua
    except Exception as e:
        logger.warning("fake-useragent unavailable, using static fallback list: %s", e)
        return None


def _get_user_agent_string(ua: Optional[UserAgent]) -> str:
    """Get a user agent string from UserAgent instance or static fallback.

    Args:
        ua: UserAgent instance or None.

    Returns:
        A user agent string.
    """
    if ua is not None:
        try:
            return ua.random
        except Exception:
            pass
    return random.choice(STATIC_USER_AGENTS)


def _map_dataframe_to_jobs(df: pd.DataFrame) -> list[Job]:
    """Convert a python-jobspy DataFrame to a list of Job dataclass instances.

    Uses safe column access with fallback to empty string for missing values.
    Logs a warning when expected columns are missing from the DataFrame.

    Args:
        df: DataFrame returned by python-jobspy's scrape_jobs.

    Returns:
        List of Job instances.
    """
    if df is None or df.empty:
        return []

    # Check for missing expected columns
    actual_columns = set(df.columns)
    expected_col_names = set(EXPECTED_COLUMNS.values())
    missing_columns = expected_col_names - actual_columns

    if missing_columns:
        logger.warning(
            "Missing expected columns in DataFrame: %s. "
            "Actual columns: %s. "
            "python-jobspy version may have changed column names.",
            sorted(missing_columns),
            sorted(actual_columns),
        )

    jobs = []
    for _, row in df.iterrows():
        job = Job(
            job_id=str(row.get(EXPECTED_COLUMNS["job_id"], "") or ""),
            title=str(row.get(EXPECTED_COLUMNS["title"], "") or ""),
            company=str(row.get(EXPECTED_COLUMNS["company"], "") or ""),
            location=str(row.get(EXPECTED_COLUMNS["location"], "") or ""),
            job_url=str(row.get(EXPECTED_COLUMNS["job_url"], "") or ""),
            description=str(row.get(EXPECTED_COLUMNS["description"], "") or ""),
            date_posted=str(row.get(EXPECTED_COLUMNS["date_posted"], "") or "") or None,
            salary=str(row.get(EXPECTED_COLUMNS["salary"], "") or "") or None,
            site=str(row.get(EXPECTED_COLUMNS["site"], "") or ""),
        )
        jobs.append(job)

    return jobs


def scrape_all_keywords(
    keywords: list[str],
    locations: list[str],
    results_per_keyword: int,
    hours_old: int,
    min_delay: float,
    max_delay: float,
) -> ScrapeResult:
    """Scrape LinkedIn for tech intern jobs across all keyword x location combinations.

    Applies rate limiting with random delays between calls and rotates user agents.
    Deduplicates results by job_url before returning. Accumulates per-combo warnings
    when exceptions occur (D-01, D-02) without crashing the pipeline.

    Blocking detection: ONLY exceptions from scrape_jobs are treated as blocking.
    Empty DataFrames (no exception) are treated as legitimate zero results.

    Args:
        keywords: List of search keywords.
        locations: List of location strings to search.
        results_per_keyword: Max results per keyword-location combination.
        hours_old: Only fetch jobs posted within this many hours.
        min_delay: Minimum seconds to wait between API calls.
        max_delay: Maximum seconds to wait between API calls.

    Returns:
        ScrapeResult with deduplicated jobs, warnings, total_combos, and blocked_combos.
    """
    # Create user agent instance ONCE before the loop
    ua = _create_user_agent()

    all_jobs: list[Job] = []
    total_combinations = len(keywords) * len(locations)
    non_empty_count = 0
    blocked_count = 0
    warnings: list[str] = []
    call_index = 0

    for keyword in keywords:
        for location in locations:
            call_index += 1
            print(f"Searching {call_index}/{total_combinations}: '{keyword}' in '{location}'...")
            logger.info(
                "Searching %d/%d: '%s' in '%s'",
                call_index, total_combinations, keyword, location,
            )

            try:
                user_agent = _get_user_agent_string(ua)
                df = scrape_jobs(
                    site_name=["linkedin"],
                    search_term=keyword,
                    location=location,
                    job_type="internship",
                    results_wanted=results_per_keyword,
                    hours_old=hours_old,
                    linkedin_fetch_description=True,
                    verbose=0,
                    user_agent=user_agent,
                )

                if df is not None and not df.empty:
                    non_empty_count += 1
                    jobs = _map_dataframe_to_jobs(df)
                    all_jobs.extend(jobs)
                    logger.info("  Found %d results for '%s' in '%s'", len(jobs), keyword, location)
                else:
                    logger.info("  No results for '%s' in '%s'", keyword, location)

            except Exception as e:
                blocked_count += 1
                warning_msg = (
                    f"Blocked: '{keyword}' in '{location}' "
                    f"-- {type(e).__name__}: {e}"
                )
                warnings.append(warning_msg)
                logger.warning(warning_msg)
                continue

            # Rate limiting: sleep between calls, skip after last
            if call_index < total_combinations:
                delay = random.uniform(min_delay, max_delay)
                logger.debug("Sleeping %.1fs before next search...", delay)
                time.sleep(delay)

    # Silent failure escalation: CRITICAL log if ALL combinations returned zero results
    # This fires when all combos are blocked OR all return empty DataFrames
    if non_empty_count == 0 and total_combinations > 0:
        logger.critical(
            "All %d keyword-location combinations returned zero results. "
            "LinkedIn may be blocking requests. "
            "Check logs and try running manually on LinkedIn.com to verify.",
            total_combinations,
        )

    # Deduplicate by job_url
    before_count = len(all_jobs)
    seen_urls: set[str] = set()
    unique_jobs: list[Job] = []

    for job in all_jobs:
        if job.job_url and job.job_url not in seen_urls:
            seen_urls.add(job.job_url)
            unique_jobs.append(job)
        elif not job.job_url:
            # Keep jobs without URLs (shouldn't happen but be safe)
            unique_jobs.append(job)

    after_count = len(unique_jobs)
    if before_count != after_count:
        logger.info("Deduplicated %d results to %d unique jobs", before_count, after_count)

    return ScrapeResult(
        jobs=unique_jobs,
        warnings=warnings,
        total_combos=total_combinations,
        blocked_combos=blocked_count,
    )
