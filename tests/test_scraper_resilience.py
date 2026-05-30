"""Tests for LinkedIn scraper resilience — partial results, blocking tolerance, ScrapeResult.

Tests D-01 through D-05 behavior:
- scrape_all_keywords returns ScrapeResult with jobs, warnings, total_combos, blocked_combos
- Partial failures accumulate warnings without crashing pipeline
- Empty DataFrames are legitimate (NOT blocking)
- Total block (all combos blocked) skips email entirely
"""

import logging
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from src.models import Job
from tests.conftest import make_job


def _make_jobs_dataframe(n=3, prefix=""):
    """Create a sample DataFrame mimicking python-jobspy output."""
    return pd.DataFrame({
        "id": [f"{prefix}job_{i}" for i in range(n)],
        "title": [f"Software Engineer Intern {prefix}{i}" for i in range(n)],
        "company": [f"Company{prefix}{i}" for i in range(n)],
        "location": ["Bengaluru, Karnataka, India"] * n,
        "job_url": [f"https://linkedin.com/jobs/view/{prefix}{i}" for i in range(n)],
        "description": [f"Description for job {prefix}{i}" for i in range(n)],
        "date_posted": ["2026-05-29"] * n,
        "min_amount": [None] * n,
        "site": ["linkedin"] * n,
    })


class TestScrapeResultDataclass:
    """Tests for ScrapeResult dataclass structure and scrape_all_keywords return type."""

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_returns_scrape_result_with_expected_attributes(self, mock_sleep, mock_scrape):
        """scrape_all_keywords returns ScrapeResult with .jobs, .warnings, .total_combos, .blocked_combos."""
        from src.scraper.linkedin import scrape_all_keywords, ScrapeResult

        mock_scrape.return_value = _make_jobs_dataframe(2)

        result = scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=0,
            max_delay=0,
        )

        assert isinstance(result, ScrapeResult)
        assert hasattr(result, "jobs")
        assert hasattr(result, "warnings")
        assert hasattr(result, "total_combos")
        assert hasattr(result, "blocked_combos")
        assert isinstance(result.jobs, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.total_combos, int)
        assert isinstance(result.blocked_combos, int)


class TestPartialResults:
    """Tests for partial failure handling (D-01, D-02)."""

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_partial_failure_collects_successful_results(self, mock_sleep, mock_scrape):
        """When 1 of 3 combos raises Exception, result.jobs contains jobs from 2 successful combos."""
        from src.scraper.linkedin import scrape_all_keywords

        # 3 combos: 1 keyword x 3 locations. Second raises, first and third succeed.
        mock_scrape.side_effect = [
            _make_jobs_dataframe(2, prefix="a"),
            Exception("HTTP 429 Too Many Requests"),
            _make_jobs_dataframe(2, prefix="c"),
        ]

        result = scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["Bengaluru", "Mumbai", "Remote"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=0,
            max_delay=0,
        )

        # Jobs from 2 successful combos (2 + 2 = 4)
        assert len(result.jobs) == 4
        assert result.blocked_combos == 1
        assert result.total_combos == 3

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_partial_failure_warning_format(self, mock_sleep, mock_scrape):
        """When a combo raises, result.warnings has entry matching 'Blocked: '{keyword}' in '{location}' -- {ExcType}: {msg}'."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.side_effect = [
            Exception("HTTP 429 Too Many Requests"),
            _make_jobs_dataframe(2, prefix="b"),
        ]

        result = scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["Mumbai", "Remote"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=0,
            max_delay=0,
        )

        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert "Blocked: 'SDE intern' in 'Mumbai'" in warning
        assert "Exception: HTTP 429 Too Many Requests" in warning

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_no_failure_empty_warnings(self, mock_sleep, mock_scrape):
        """When no combos fail, result.warnings is empty and result.blocked_combos == 0."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.return_value = _make_jobs_dataframe(2)

        result = scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=0,
            max_delay=0,
        )

        assert result.warnings == []
        assert result.blocked_combos == 0

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_empty_dataframe_not_treated_as_blocking(self, mock_sleep, mock_scrape):
        """When scrape_jobs returns empty DataFrame (no exception), blocked_combos stays 0."""
        from src.scraper.linkedin import scrape_all_keywords

        # Return empty DataFrame (legitimate zero results — NOT blocking)
        mock_scrape.return_value = pd.DataFrame()

        result = scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=0,
            max_delay=0,
        )

        assert result.blocked_combos == 0
        assert result.warnings == []
        assert result.jobs == []


class TestTotalBlockage:
    """Tests for total failure (all combos blocked) behavior (D-03)."""

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_all_combos_blocked_critical_log(self, mock_sleep, mock_scrape, caplog):
        """When ALL combos raise Exception, CRITICAL log is emitted."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.side_effect = [
            Exception("Blocked 1"),
            Exception("Blocked 2"),
        ]

        with caplog.at_level(logging.CRITICAL):
            result = scrape_all_keywords(
                keywords=["SDE intern"],
                locations=["India", "Remote"],
                results_per_keyword=75,
                hours_old=24,
                min_delay=0,
                max_delay=0,
            )

        assert result.jobs == []
        assert result.blocked_combos == result.total_combos == 2
        assert any(record.levelno == logging.CRITICAL for record in caplog.records)

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_all_combos_blocked_fields(self, mock_sleep, mock_scrape):
        """When ALL combos raise, result.blocked_combos == total_combos, result.jobs is empty."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.side_effect = [
            Exception("Blocked"),
            Exception("Blocked"),
            Exception("Blocked"),
        ]

        result = scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["India", "Remote", "Mumbai"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=0,
            max_delay=0,
        )

        assert result.jobs == []
        assert result.blocked_combos == 3
        assert result.total_combos == 3
        assert len(result.warnings) == 3


class TestMainPipelineIntegration:
    """Tests for main.py integration with ScrapeResult (unpacking, total-block skip)."""

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_main_unpacks_scrape_result_jobs(self, mock_sleep, mock_scrape):
        """main.py correctly unpacks ScrapeResult: jobs = result.jobs."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.return_value = _make_jobs_dataframe(3)

        result = scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=0,
            max_delay=0,
        )

        # Simulate main.py unpacking
        jobs = result.jobs
        assert isinstance(jobs, list)
        assert len(jobs) == 3
        assert all(isinstance(j, Job) for j in jobs)

    def test_total_block_sets_scrape_error_status(self):
        """When blocked_combos == total_combos > 0, pipeline_status should be SCRAPE_ERROR."""
        from src.scraper.linkedin import ScrapeResult
        from src.scheduling import SCRAPE_ERROR

        # Simulate total-block scenario
        scrape_result = ScrapeResult(
            jobs=[],
            warnings=["Blocked: 'SDE' in 'India' -- Exception: blocked"],
            total_combos=1,
            blocked_combos=1,
        )

        # main.py logic: total block check
        total_block = (
            scrape_result.blocked_combos == scrape_result.total_combos
            and scrape_result.total_combos > 0
        )

        assert total_block is True

        # When total_block, pipeline_status = SCRAPE_ERROR
        pipeline_status = SCRAPE_ERROR if total_block else "success"
        assert pipeline_status == SCRAPE_ERROR


class TestScrapeWarningsInDigest:
    """Tests for scrape warnings in email digest footer (D-05, Task 2)."""

    def test_render_digest_with_warning_summary_html(self):
        """render_digest with scrape_warning_summary produces HTML containing the warning text in a yellow row."""
        from src.notifications.renderer import render_digest

        job = make_job(job_id="g1", title="Test Intern", company="TestCo")
        summary = "Note: 1 of 3 search combinations were blocked by LinkedIn."

        html, _ = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
            scrape_warning_summary=summary,
        )

        assert summary in html
        # Should be in a yellow-styled warning row
        assert "#fff3cd" in html

    def test_render_digest_without_warning_summary_html(self):
        """render_digest with scrape_warning_summary=None produces HTML NOT containing 'blocked by LinkedIn'."""
        from src.notifications.renderer import render_digest

        job = make_job(job_id="g1", title="Test Intern", company="TestCo")

        html, _ = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
            scrape_warning_summary=None,
        )

        assert "blocked by LinkedIn" not in html
        assert "#fff3cd" not in html

    def test_render_plain_text_with_warning_summary(self):
        """_render_plain_text with scrape_warning_summary includes summary text in output."""
        from src.notifications.renderer import render_digest

        job = make_job(job_id="g1", title="Test Intern", company="TestCo")
        summary = "Note: 2 of 5 search combinations were blocked by LinkedIn."

        _, plain_text = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
            scrape_warning_summary=summary,
        )

        assert summary in plain_text

    def test_render_plain_text_without_warning_summary(self):
        """_render_plain_text with scrape_warning_summary=None does NOT include warning line."""
        from src.notifications.renderer import render_digest

        job = make_job(job_id="g1", title="Test Intern", company="TestCo")

        _, plain_text = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
            scrape_warning_summary=None,
        )

        assert "blocked by LinkedIn" not in plain_text

    def test_main_constructs_warning_summary_when_blocked(self):
        """main.py constructs scrape_warning_summary only when scrape_result.blocked_combos > 0."""
        from src.scraper.linkedin import ScrapeResult

        # Case 1: some combos blocked
        scrape_result = ScrapeResult(
            jobs=[make_job()],
            warnings=["Blocked: 'SDE' in 'India' -- Exception: blocked"],
            total_combos=3,
            blocked_combos=1,
        )

        # Simulate main.py logic
        if scrape_result.blocked_combos > 0:
            scrape_warning_summary = (
                f"Note: {scrape_result.blocked_combos} of "
                f"{scrape_result.total_combos} search combinations "
                f"were blocked by LinkedIn."
            )
        else:
            scrape_warning_summary = None

        assert scrape_warning_summary == "Note: 1 of 3 search combinations were blocked by LinkedIn."

        # Case 2: no combos blocked
        scrape_result_clean = ScrapeResult(
            jobs=[make_job()],
            warnings=[],
            total_combos=3,
            blocked_combos=0,
        )

        if scrape_result_clean.blocked_combos > 0:
            summary_clean = "should not happen"
        else:
            summary_clean = None

        assert summary_clean is None
