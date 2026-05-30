"""Scheduling module for LinkedInScript -- run tracking, catch-up, health monitoring.

Provides runtime intelligence for unattended daily execution:
- Run tracking with explicit status taxonomy
- Catch-up detection when last run was >24h ago
- Health alerts on consecutive scrape failures (NOT zero-result days)
- Status CLI with graceful degradation

Status taxonomy (application-enforced):
    - 'running': Pipeline started, not yet completed
    - 'success': Jobs found and processed normally
    - 'zero_results': Scraper found jobs but none were new after filtering
    - 'scrape_error': Scraper returned zero results across all combinations
    - 'pipeline_error': Uncaught exception crashed the pipeline

Public API:
    record_run_start(run_id) -> None
    record_run_complete(run_id, status, jobs_found, jobs_notified) -> None
    check_catchup() -> None
    check_health(config) -> None
    print_status(config) -> None
    get_consecutive_failures() -> int
    get_last_run_time() -> str | None
"""

# Status constants
SUCCESS = "success"
ZERO_RESULTS = "zero_results"
SCRAPE_ERROR = "scrape_error"
PIPELINE_ERROR = "pipeline_error"

from src.scheduling.runs import (
    record_run_start,
    record_run_complete,
    get_consecutive_failures,
    get_last_run_time,
    check_catchup,
)
from src.scheduling.health import check_health, print_status

__all__ = [
    "SUCCESS",
    "ZERO_RESULTS",
    "SCRAPE_ERROR",
    "PIPELINE_ERROR",
    "record_run_start",
    "record_run_complete",
    "get_consecutive_failures",
    "get_last_run_time",
    "check_catchup",
    "check_health",
    "print_status",
]
