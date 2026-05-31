"""Shared test fixtures for LinkedInScript tests."""

import pytest

from src.models import Job


# ---------------------------------------------------------------------------
# Shared test factories
# ---------------------------------------------------------------------------


def make_job(
    job_id: str = "test-001",
    title: str = "Software Intern",
    company: str = "TestCorp",
    location: str = "Bengaluru, Karnataka, India",
    job_url: str = "https://linkedin.com/jobs/1",
    description: str = "Test description",
    date_posted: str = "2025-01-01",
    salary: str | None = None,
    site: str = "linkedin",
    watchlist_match: bool = False,
) -> Job:
    """Create a Job instance with sensible defaults, overridable via kwargs."""
    return Job(
        job_id=job_id,
        title=title,
        company=company,
        location=location,
        job_url=job_url,
        description=description,
        date_posted=date_posted,
        salary=salary,
        site=site,
        watchlist_match=watchlist_match,
    )


@pytest.fixture
def sample_config():
    """Return a valid configuration dict matching config.example.yaml structure."""
    return {
        "search": {
            "keywords": [
                "software engineer intern",
                "SDE intern",
                "data science intern",
            ],
            "locations": [
                "Bengaluru, Karnataka, India",
                "India",
            ],
            "results_wanted": 75,
            "hours_old": 24,
        },
        "scraping": {
            "min_delay": 5,
            "max_delay": 12,
        },
        "companies": {
            "watchlist": ["Google", "Microsoft"],
            "blocklist": ["TCS", "Infosys"],
        },
        "filters": {
            "min_salary_monthly": 30000,
        },
        "email": {
            "enabled": False,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "sender_email": "user@gmail.com",
            "recipient_email": "user@gmail.com",
        },
        "logging": {
            "level": "INFO",
            "file": "logs/run.log",
            "max_size_mb": 5,
            "backup_count": 3,
        },
        "schedule": {
            "time": "08:00",
        },
    }
