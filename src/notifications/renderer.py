from __future__ import annotations

"""Notification renderer — Jinja2 template loading and digest rendering.

Renders HTML and plain-text versions of the daily job digest email.
Uses absolute path resolution for template directory (Task Scheduler compatibility).

Exports:
    render_digest(watchlist_jobs, general_jobs, repost_jobs, subject, date_str) -> tuple[str, str]
    prepare_email_data(new_jobs, repost_ids) -> tuple[list, list, list]
    make_subject(job_count) -> str
    _make_snippet(description) -> str
"""

import logging
import textwrap
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models import Job

logger = logging.getLogger(__name__)

# Absolute path resolution for Task Scheduler compatibility (review concern 6)
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _make_snippet(description: str | None) -> str:
    """Truncate job description to a readable snippet.

    CRITICAL (review concern 4): handles None and empty string gracefully.

    Args:
        description: Raw job description text, may be None or empty.

    Returns:
        Truncated snippet (~150 chars) or fallback text.
    """
    if not description:
        return "No description available."

    return textwrap.shorten(description, width=150, placeholder="...")


def make_subject(job_count: int) -> str:
    """Generate email subject line per D-04 format.

    Args:
        job_count: Number of new jobs found.

    Returns:
        Subject line: "LinkedInScript: N new internships found (Mon DD)"
        or "LinkedInScript: No new internships (Mon DD)" when count is 0.
    """
    today = date.today().strftime("%b %d")
    if job_count == 0:
        return f"LinkedInScript: No new internships ({today})"
    return f"LinkedInScript: {job_count} new internships found ({today})"


def prepare_email_data(new_jobs: list, repost_ids: set) -> tuple[list, list, list]:
    """Split jobs into sections for email template.

    Per D-05: Watchlist first, then general, then reposts.

    Args:
        new_jobs: List of Job instances from the pipeline.
        repost_ids: Set of job_ids identified as reposts.

    Returns:
        Tuple of (watchlist_jobs, general_jobs, repost_jobs).
    """
    watchlist_jobs = []
    general_jobs = []
    repost_jobs = []

    for job in new_jobs:
        if job.job_id in repost_ids:
            repost_jobs.append(job)
        elif job.watchlist_match:
            watchlist_jobs.append(job)
        else:
            general_jobs.append(job)

    return watchlist_jobs, general_jobs, repost_jobs


def render_digest(
    watchlist_jobs: list,
    general_jobs: list,
    repost_jobs: list,
    subject: str,
    date_str: str,
    scrape_warning_summary: str | None = None,
    fallback_note: str | None = None,
) -> tuple[str, str]:
    """Render HTML and plain-text versions of the digest email.

    Args:
        watchlist_jobs: Jobs from watchlist companies.
        general_jobs: Non-watchlist, non-repost jobs.
        repost_jobs: Jobs identified as reposts.
        subject: Email subject line.
        date_str: Human-readable date string for footer.
        scrape_warning_summary: Optional warning text for footer when combos were blocked (D-05).
        fallback_note: Optional note when previous fallback file exists (D-09).

    Returns:
        Tuple of (html_body, plain_text_body).
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("digest.html")

    # Prepare snippet data for template
    watchlist_data = [_prepare_job_data(job) for job in watchlist_jobs]
    general_data = [_prepare_job_data(job) for job in general_jobs]
    repost_data = [_prepare_job_data(job) for job in repost_jobs]

    html = template.render(
        watchlist_jobs=watchlist_data,
        general_jobs=general_data,
        repost_jobs=repost_data,
        subject=subject,
        date=date_str,
        scrape_warning_summary=scrape_warning_summary,
        fallback_note=fallback_note,
    )

    # Plain-text fallback (review concern 3, D-08 dry-run console preview)
    plain_text = _render_plain_text(
        watchlist_jobs, general_jobs, repost_jobs, subject, date_str,
        scrape_warning_summary=scrape_warning_summary,
        fallback_note=fallback_note,
    )

    return html, plain_text


def _prepare_job_data(job: Job) -> dict:
    """Prepare a job for template rendering with snippet.

    Args:
        job: Job dataclass instance.

    Returns:
        Dict with job fields plus computed snippet.
    """
    return {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "job_url": job.job_url,
        "snippet": _make_snippet(job.description),
        "date_posted": job.date_posted or "Date not available",
        "watchlist_match": job.watchlist_match,
    }


def _render_plain_text(
    watchlist_jobs: list,
    general_jobs: list,
    repost_jobs: list,
    subject: str,
    date_str: str,
    scrape_warning_summary: str | None = None,
    fallback_note: str | None = None,
) -> str:
    """Render plain-text version of the digest for console preview and email fallback.

    Args:
        watchlist_jobs: Jobs from watchlist companies.
        general_jobs: Non-watchlist, non-repost jobs.
        repost_jobs: Jobs identified as reposts.
        subject: Email subject line.
        date_str: Human-readable date string.
        scrape_warning_summary: Optional warning text when combos were blocked (D-05).
        fallback_note: Optional note when previous fallback file exists (D-09).

    Returns:
        Plain-text string with section headers and job details.
    """
    lines = [subject, "=" * len(subject), ""]

    total_jobs = len(watchlist_jobs) + len(general_jobs) + len(repost_jobs)

    if total_jobs == 0:
        lines.append(
            "No new internships found today. The tool ran successfully "
            "-- this is your daily heartbeat."
        )
        lines.append("")
        if scrape_warning_summary:
            lines.append(scrape_warning_summary)
            lines.append("")
        if fallback_note:
            lines.append(fallback_note)
            lines.append("")
        lines.append(f"Report date: {date_str}")
        return "\n".join(lines)

    if watchlist_jobs:
        lines.append("--- Priority Companies (Watchlist) ---")
        lines.append("")
        for job in watchlist_jobs:
            lines.append(f"  [WATCHLIST] {job.title}")
            lines.append(f"    Company:  {job.company}")
            lines.append(f"    Location: {job.location}")
            lines.append(f"    URL:      {job.job_url}")
            lines.append(f"    Snippet:  {_make_snippet(job.description)}")
            lines.append(f"    Posted:   {job.date_posted or 'Date not available'}")
            lines.append("")

    if general_jobs:
        lines.append("--- New Listings ---")
        lines.append("")
        for job in general_jobs:
            lines.append(f"  {job.title}")
            lines.append(f"    Company:  {job.company}")
            lines.append(f"    Location: {job.location}")
            lines.append(f"    URL:      {job.job_url}")
            lines.append(f"    Snippet:  {_make_snippet(job.description)}")
            lines.append(f"    Posted:   {job.date_posted or 'Date not available'}")
            lines.append("")

    if repost_jobs:
        lines.append("--- Reposts ---")
        lines.append("")
        for job in repost_jobs:
            lines.append(f"  [REPOST] {job.title}")
            lines.append(f"    Company:  {job.company}")
            lines.append(f"    Location: {job.location}")
            lines.append(f"    URL:      {job.job_url}")
            lines.append(f"    Snippet:  {_make_snippet(job.description)}")
            lines.append(f"    Posted:   {job.date_posted or 'Date not available'}")
            lines.append("")

    if scrape_warning_summary:
        lines.append(scrape_warning_summary)
        lines.append("")

    if fallback_note:
        lines.append(fallback_note)
        lines.append("")

    lines.append(f"Report date: {date_str}")
    return "\n".join(lines)
