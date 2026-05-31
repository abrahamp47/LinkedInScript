"""Notifications module for LinkedInScript — email digest rendering and delivery.

Public API:
    send_digest(config, new_jobs, repost_ids) -> None
    render_digest(watchlist_jobs, general_jobs, repost_jobs, subject, date_str) -> tuple[str, str]
    prepare_email_data(new_jobs, repost_ids) -> tuple[list, list, list]
    make_subject(job_count) -> str
    send_email(config, subject, html_body, text_body) -> None
    send_test_email(config) -> None

Implements NOTF-01: HTML email digest with title, company, link, snippet, location, date.
Implements NOTF-02: Digest sectioned — watchlist first, then general, then reposts.
Implements SETUP-01: --test-email verifies SMTP configuration.
Implements NOTF-04: --dry-run prints digest without sending.
"""

from datetime import date

from src.notifications.renderer import (
    make_subject,
    prepare_email_data,
    render_digest,
    _make_snippet,
)
from src.notifications.sender import send_email, send_test_email


def send_digest(config: dict, new_jobs: list, repost_ids: set) -> None:
    """High-level: prepare email data, render, and send digest.

    Orchestrates the full email flow: split jobs into sections,
    generate subject, render HTML + plain-text, and send via SMTP.

    Args:
        config: Full config dict with 'email' section.
        new_jobs: List of new Job instances from the pipeline.
        repost_ids: Set of job_ids identified as reposts.

    Raises:
        smtplib.SMTPException: On SMTP failure.
        ValueError: If EMAIL_PASSWORD is not set.
    """
    watchlist_jobs, general_jobs, repost_jobs = prepare_email_data(new_jobs, repost_ids)
    subject = make_subject(len(new_jobs))
    date_str = date.today().strftime("%B %d, %Y")

    html, text = render_digest(watchlist_jobs, general_jobs, repost_jobs, subject, date_str)
    send_email(config, subject, html, text)


__all__ = [
    "send_digest",
    "render_digest",
    "prepare_email_data",
    "make_subject",
    "send_email",
    "send_test_email",
]
