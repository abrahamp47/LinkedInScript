"""Unit tests for src/scraper/linkedin.py — scraping, UA rotation, column mapping, dedup."""

import logging
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from src.models import Job


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


class TestScrapeAllKeywords:
    """Tests for scrape_all_keywords function."""

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_calls_per_keyword_location_combination(self, mock_sleep, mock_scrape):
        """Test 1: scrape_all_keywords calls scrape_jobs once per keyword x location combination."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.return_value = _make_jobs_dataframe(2)

        keywords = ["SDE intern", "ML intern"]
        locations = ["Bengaluru, Karnataka, India", "India"]

        scrape_all_keywords(
            keywords=keywords,
            locations=locations,
            results_per_keyword=75,
            hours_old=24,
            min_delay=5,
            max_delay=12,
        )

        # 2 keywords x 2 locations = 4 calls
        assert mock_scrape.call_count == 4

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_passes_correct_params_to_scrape_jobs(self, mock_sleep, mock_scrape):
        """Test 2: scrape_all_keywords passes correct params including site_name, job_type, results_wanted, hours_old."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.return_value = _make_jobs_dataframe(1)

        scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=48,
            min_delay=5,
            max_delay=12,
        )

        call_kwargs = mock_scrape.call_args[1]
        assert call_kwargs["site_name"] == ["linkedin"]
        assert call_kwargs["job_type"] == "internship"
        assert call_kwargs["results_wanted"] == 75
        assert call_kwargs["hours_old"] == 48

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    @patch("src.scraper.linkedin.random.uniform", return_value=7.5)
    def test_sleeps_between_calls(self, mock_uniform, mock_sleep, mock_scrape):
        """Test 3: scrape_all_keywords sleeps between calls with delay in range [min_delay, max_delay]."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.return_value = _make_jobs_dataframe(1)

        scrape_all_keywords(
            keywords=["SDE intern", "ML intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=5,
            max_delay=12,
        )

        # 2 calls, sleep between them (not after last)
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(7.5)
        mock_uniform.assert_called_with(5, 12)

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_sets_user_agent_on_each_call(self, mock_sleep, mock_scrape):
        """Test 4: scrape_all_keywords sets a user_agent string on each call."""
        from src.scraper.linkedin import scrape_all_keywords

        mock_scrape.return_value = _make_jobs_dataframe(1)

        scrape_all_keywords(
            keywords=["SDE intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=5,
            max_delay=12,
        )

        call_kwargs = mock_scrape.call_args[1]
        assert "user_agent" in call_kwargs
        assert call_kwargs["user_agent"] is not None
        assert isinstance(call_kwargs["user_agent"], str)
        assert len(call_kwargs["user_agent"]) > 10

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_handles_exception_gracefully(self, mock_sleep, mock_scrape):
        """Test 5: scrape_all_keywords handles scrape_jobs raising exception gracefully."""
        from src.scraper.linkedin import scrape_all_keywords

        # First call raises, second succeeds
        mock_scrape.side_effect = [
            Exception("Network error"),
            _make_jobs_dataframe(2),
        ]

        result = scrape_all_keywords(
            keywords=["SDE intern", "ML intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=5,
            max_delay=12,
        )

        # Should still return results from the successful call
        assert len(result.jobs) == 2
        assert mock_scrape.call_count == 2


class TestMapDataframeToJobs:
    """Tests for _map_dataframe_to_jobs function."""

    def test_converts_dataframe_to_job_instances(self):
        """Test 6: _map_dataframe_to_jobs converts DataFrame rows to Job dataclass instances."""
        from src.scraper.linkedin import _map_dataframe_to_jobs

        df = _make_jobs_dataframe(2)
        jobs = _map_dataframe_to_jobs(df)

        assert len(jobs) == 2
        assert all(isinstance(j, Job) for j in jobs)
        assert jobs[0].title == "Software Engineer Intern 0"
        assert jobs[0].company == "Company0"
        assert jobs[0].job_url == "https://linkedin.com/jobs/view/0"
        assert jobs[0].site == "linkedin"

    def test_logs_warning_on_missing_columns(self, caplog):
        """Test 7: _map_dataframe_to_jobs logs warning when expected columns are missing."""
        from src.scraper.linkedin import _map_dataframe_to_jobs

        # DataFrame with unexpected column names
        df = pd.DataFrame({
            "weird_title": ["Test Job"],
            "weird_company": ["TestCo"],
        })

        with caplog.at_level(logging.WARNING):
            jobs = _map_dataframe_to_jobs(df)

        # Should still return Job(s) with empty fields
        assert len(jobs) == 1
        assert jobs[0].title == ""
        # Should have logged a warning about missing columns
        assert any("missing" in record.message.lower() or "column" in record.message.lower()
                   for record in caplog.records)


class TestDeduplication:
    """Tests for URL-based deduplication in scrape_all_keywords."""

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_deduplicates_by_job_url(self, mock_sleep, mock_scrape):
        """Test 8: scrape_all_keywords deduplicates results by job_url before returning."""
        from src.scraper.linkedin import scrape_all_keywords

        # Both calls return overlapping jobs (same URLs)
        df1 = _make_jobs_dataframe(3, prefix="")
        df2 = _make_jobs_dataframe(3, prefix="")  # Same URLs as df1

        mock_scrape.side_effect = [df1, df2]

        result = scrape_all_keywords(
            keywords=["SDE intern", "ML intern"],
            locations=["India"],
            results_per_keyword=75,
            hours_old=24,
            min_delay=5,
            max_delay=12,
        )

        # Should have 3 unique jobs (not 6)
        assert len(result.jobs) == 3


class TestCriticalLogging:
    """Tests for CRITICAL log on all-empty results."""

    @patch("src.scraper.linkedin.scrape_jobs")
    @patch("src.scraper.linkedin.time.sleep")
    def test_logs_critical_when_all_empty(self, mock_sleep, mock_scrape, caplog):
        """Test 9: scrape_all_keywords logs CRITICAL when ALL combinations return zero results."""
        from src.scraper.linkedin import scrape_all_keywords

        # All calls return empty DataFrames
        mock_scrape.return_value = pd.DataFrame()

        with caplog.at_level(logging.CRITICAL):
            result = scrape_all_keywords(
                keywords=["SDE intern", "ML intern"],
                locations=["India"],
                results_per_keyword=75,
                hours_old=24,
                min_delay=5,
                max_delay=12,
            )

        assert len(result.jobs) == 0
        assert any(record.levelno == logging.CRITICAL for record in caplog.records)


class TestCreateUserAgent:
    """Tests for _create_user_agent function."""

    def test_create_user_agent_returns_instance_or_falls_back(self):
        """Test 10: _create_user_agent returns a UserAgent instance or falls back to static list on exception."""
        from src.scraper.linkedin import _create_user_agent, STATIC_USER_AGENTS

        # Test that the function returns either a UserAgent or None
        result = _create_user_agent()
        # Either it's a UserAgent instance or None (fallback to static list)
        if result is None:
            # Fallback mode - verify static list exists
            assert len(STATIC_USER_AGENTS) >= 5
        else:
            # Should have a .random attribute
            assert hasattr(result, "random")

    @patch("src.scraper.linkedin.UserAgent", side_effect=Exception("Network error"))
    def test_create_user_agent_falls_back_on_exception(self, mock_ua):
        """_create_user_agent returns None when UserAgent raises exception."""
        from src.scraper.linkedin import _create_user_agent

        result = _create_user_agent()
        assert result is None
