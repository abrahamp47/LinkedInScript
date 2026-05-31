from __future__ import annotations

"""Data models for LinkedInScript."""

from dataclasses import dataclass, field


@dataclass
class Job:
    """Represents a single job listing scraped from LinkedIn.

    All string fields default to empty string; optional fields default to None.
    """

    job_id: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    job_url: str = ""
    description: str = ""
    date_posted: str | None = None
    salary: str | None = None
    site: str = ""
    watchlist_match: bool = False
