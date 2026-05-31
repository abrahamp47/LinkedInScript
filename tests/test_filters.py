"""Tests for the filter pipeline — location, company, and pipeline modules.

RED phase: These tests define expected behavior for the filter pipeline.
They MUST fail initially (ImportError) since src/filters/location.py,
src/filters/company.py, and src/filters/pipeline.py do not yet exist.
"""

import logging

import pytest

from src.models import Job
from src.filters.location import filter_by_location
from src.filters.company import filter_by_company, apply_watchlist
from src.filters.pipeline import run_filter_pipeline, FilterResult


# ---------------------------------------------------------------------------
# Helper
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


# Default test fixtures for location filter
DEFAULT_LOCATION_ALIASES = [
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

DEFAULT_REMOTE_KEYWORDS = [
    "remote",
    "work from home",
    "wfh",
    "pan india",
    "anywhere in india",
    "hybrid",
]


# ===========================================================================
# Location Filter Tests
# ===========================================================================

class TestLocationFilter:
    """Tests for filter_by_location function."""

    def test_bengaluru_karnataka_india_passes(self):
        """Job with 'Bengaluru, Karnataka, India' should pass."""
        jobs = [make_job(location="Bengaluru, Karnataka, India")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_bangalore_karnataka_india_passes(self):
        """Job with 'Bangalore, Karnataka, India' should pass."""
        jobs = [make_job(location="Bangalore, Karnataka, India")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_whitefield_bengaluru_passes(self):
        """Job with 'Whitefield, Bengaluru' should pass (neighborhood alias per D-02)."""
        jobs = [make_job(location="Whitefield, Bengaluru")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_electronic_city_bangalore_passes(self):
        """Job with 'Electronic City, Bangalore' should pass."""
        jobs = [make_job(location="Electronic City, Bangalore")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_remote_passes(self):
        """Job with 'Remote' should pass (remote keyword per D-03)."""
        jobs = [make_job(location="Remote")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_work_from_home_passes(self):
        """Job with 'Work from Home' should pass."""
        jobs = [make_job(location="Work from Home")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_pan_india_passes(self):
        """Job with 'Pan India' should pass."""
        jobs = [make_job(location="Pan India")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_hyderabad_rejected(self):
        """Job with 'Hyderabad, Telangana, India' should be rejected."""
        jobs = [make_job(location="Hyderabad, Telangana, India")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 0
        assert len(rejected) == 1

    def test_karnataka_alone_passes(self):
        """Job with 'Karnataka, India' should pass (per D-04)."""
        jobs = [make_job(location="Karnataka, India")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_mumbai_rejected(self):
        """Job with 'Mumbai, Maharashtra, India' should be rejected."""
        jobs = [make_job(location="Mumbai, Maharashtra, India")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 0
        assert len(rejected) == 1

    def test_bangalore_road_hubli_rejected(self):
        """Job with 'Bangalore Road, Hubli' should be REJECTED (false positive).

        The two-tier algorithm must reject this because comma-split isolates
        segments ['Bangalore Road', 'Hubli']. 'bangalore road' != 'bangalore'
        (exact segment match) and 'hubli' is not in aliases. REJECTED.
        """
        jobs = [make_job(location="Bangalore Road, Hubli")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 0
        assert len(rejected) == 1

    def test_none_location_passes(self):
        """Job with location=None should pass (None guard - do not reject)."""
        jobs = [make_job(location=None)]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_empty_location_passes(self):
        """Job with location='' should pass (empty guard - do not reject)."""
        jobs = [make_job(location="")]
        passed, rejected = filter_by_location(jobs, DEFAULT_LOCATION_ALIASES, DEFAULT_REMOTE_KEYWORDS)
        assert len(passed) == 1
        assert len(rejected) == 0


# ===========================================================================
# Company Filter Tests
# ===========================================================================

class TestCompanyFilter:
    """Tests for filter_by_company and apply_watchlist functions."""

    def test_blocklist_rejects_exact_match(self):
        """Job from 'TCS' with blocklist=['TCS'] should be rejected (per D-05)."""
        jobs = [make_job(company="TCS")]
        passed, rejected = filter_by_company(jobs, ["TCS"])
        assert len(passed) == 0
        assert len(rejected) == 1

    def test_blocklist_rejects_substring_match(self):
        """Job from 'TCS Digital' with blocklist=['TCS'] should be rejected (substring match per D-05)."""
        jobs = [make_job(company="TCS Digital")]
        passed, rejected = filter_by_company(jobs, ["TCS"])
        assert len(passed) == 0
        assert len(rejected) == 1

    def test_blocklist_none_company_passes(self):
        """Job with company=None and blocklist=['TCS'] should pass (None guard)."""
        jobs = [make_job(company=None)]
        passed, rejected = filter_by_company(jobs, ["TCS"])
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_blocklist_empty_company_passes(self):
        """Job with company='' and blocklist=['TCS'] should pass (empty guard)."""
        jobs = [make_job(company="")]
        passed, rejected = filter_by_company(jobs, ["TCS"])
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_watchlist_flags_matching_company(self):
        """Job from 'Google India' with watchlist=['Google'] gets watchlist_match=True (per D-06, D-07)."""
        jobs = [make_job(company="Google India")]
        result = apply_watchlist(jobs, ["Google"])
        assert result[0].watchlist_match is True

    def test_watchlist_no_match_stays_false(self):
        """Job from 'Razorpay' (not on watchlist) keeps watchlist_match=False."""
        jobs = [make_job(company="Razorpay")]
        result = apply_watchlist(jobs, ["Google"])
        assert result[0].watchlist_match is False

    def test_watchlist_none_company_stays_false(self):
        """Job with company=None and watchlist=['Google'] keeps watchlist_match=False (None guard)."""
        jobs = [make_job(company=None)]
        result = apply_watchlist(jobs, ["Google"])
        assert result[0].watchlist_match is False


# ===========================================================================
# Pipeline Tests
# ===========================================================================

class TestFilterPipeline:
    """Tests for run_filter_pipeline function."""

    @pytest.fixture
    def pipeline_config(self):
        """Config dict for pipeline tests."""
        return {
            "filters": {
                "location_aliases": DEFAULT_LOCATION_ALIASES,
                "remote_keywords": DEFAULT_REMOTE_KEYWORDS,
                "min_salary_monthly": 30000,
            },
            "companies": {
                "blocklist": ["TCS", "Infosys"],
                "watchlist": ["Google", "Microsoft"],
            },
        }

    def test_pipeline_order_location_company_watchlist(self, pipeline_config):
        """Pipeline runs Location -> Company -> Watchlist -> Salary order (D-11 corrected for D-09).

        Location-rejected jobs should not appear in company stats,
        and watchlist is applied after company filter.
        """
        jobs = [
            make_job(job_id="1", location="Bengaluru, Karnataka, India", company="Google India"),
            make_job(job_id="2", location="Mumbai, India", company="Razorpay"),
            make_job(job_id="3", location="Bengaluru, Karnataka, India", company="TCS"),
        ]
        result = run_filter_pipeline(jobs, pipeline_config)

        assert isinstance(result, FilterResult)
        # Job 1 passes (Bangalore + Google watchlist)
        # Job 2 rejected by location
        # Job 3 rejected by company (TCS on blocklist)
        assert len(result.passed) == 1
        assert result.passed[0].job_id == "1"
        assert result.passed[0].watchlist_match is True
        assert result.stats["total_in"] == 3
        assert result.stats["total_out"] == 1
        assert result.stats["location_rejected"] == 1
        assert result.stats["company_rejected"] == 1
        assert result.stats["watchlist_boosted"] == 1

    def test_pipeline_logs_rejections_at_debug(self, pipeline_config, caplog):
        """Rejected jobs produce a debug log message with reason (per D-12)."""
        jobs = [make_job(location="Mumbai, Maharashtra, India")]
        with caplog.at_level(logging.DEBUG, logger="src.filters.location"):
            run_filter_pipeline(jobs, pipeline_config)
        assert any("Rejected" in record.message for record in caplog.records)

    def test_pipeline_logs_summary_at_info(self, pipeline_config, caplog):
        """Pipeline summary log at INFO level shows filter counts (per D-13)."""
        jobs = [make_job(location="Bengaluru, Karnataka, India")]
        with caplog.at_level(logging.INFO, logger="src.filters.pipeline"):
            run_filter_pipeline(jobs, pipeline_config)
        assert any("Filtered" in record.message for record in caplog.records)

    def test_pipeline_empty_list_returns_empty_result(self, pipeline_config):
        """Empty job list returns FilterResult with passed=[] and stats all zero."""
        result = run_filter_pipeline([], pipeline_config)
        assert isinstance(result, FilterResult)
        assert result.passed == []
        assert result.stats["total_in"] == 0
        assert result.stats["total_out"] == 0
        assert result.stats["location_rejected"] == 0
        assert result.stats["company_rejected"] == 0
        assert result.stats["watchlist_boosted"] == 0


# ===========================================================================
# Salary Parsing Tests
# ===========================================================================


class TestSalaryParsing:
    """Tests for parse_salary_to_monthly function.

    Covers all Indian salary formats: monthly, K-suffix, LPA, L/yr,
    lakh/lac/lakhs variants, ranges (lower bound), currency prefixes,
    bare numbers, and invalid inputs.
    """

    @pytest.fixture(autouse=True)
    def _import_salary(self):
        """Import salary module; raises ImportError if not yet created (RED phase)."""
        from src.filters.salary import parse_salary_to_monthly
        self.parse_salary_to_monthly = parse_salary_to_monthly

    @pytest.mark.parametrize(
        "salary_str,expected",
        [
            # Standard monthly formats
            ("30,000/month", 30000),
            ("Rs. 45,000/month", 45000),
            # K-suffix with monthly indicator
            ("30K/mo", 30000),
            # K-suffix alone (assume monthly - addresses review concern)
            ("30K", 30000),
            # LPA formats
            ("3.6 LPA", 30000),
            ("3.6 lpa", 30000),  # case insensitive
            ("4.8 LPA", 40000),
            # L/yr format (addresses review concern - real LinkedIn India format)
            ("3.6L/yr", 30000),
            # Lakh/lac variants with per annum (addresses review concern)
            ("6 lakh per annum", 50000),
            ("6 lakhs p.a.", 50000),
            ("3 lac per annum", 25000),
            # Ranges - uses LOWER bound (addresses review concern)
            ("3-5 LPA", 25000),
            ("25,000 - 45,000/month", 25000),
            # Currency prefix formats
            ("INR 30,000", 30000),
            ("Rs 30000", 30000),
            # Bare number (assume monthly if >= 5000)
            ("45000", 45000),
            # Bare number below threshold returns None
            ("4000", None),
            # Invalid/unparseable inputs
            (None, None),
            ("", None),
            ("competitive", None),
            ("best in industry", None),
        ],
    )
    def test_parse_salary_to_monthly(self, salary_str, expected):
        """Parametrized: parse_salary_to_monthly handles all Indian salary formats."""
        result = self.parse_salary_to_monthly(salary_str)
        assert result == expected, (
            f"parse_salary_to_monthly({salary_str!r}) returned {result}, expected {expected}"
        )


# ===========================================================================
# Salary Filter Tests
# ===========================================================================


class TestSalaryFilter:
    """Tests for filter_by_salary function.

    Covers D-08 (missing salary passes), D-09 (watchlist bypass),
    and D-12 (debug log on rejection).
    """

    @pytest.fixture(autouse=True)
    def _import_salary(self):
        """Import salary module; raises ImportError if not yet created (RED phase)."""
        from src.filters.salary import filter_by_salary
        self.filter_by_salary = filter_by_salary

    def test_missing_salary_passes(self):
        """Job with salary=None should pass (per D-08: missing salary = include)."""
        jobs = [make_job(salary=None)]
        passed, rejected = self.filter_by_salary(jobs, min_salary_monthly=30000)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_empty_salary_passes(self):
        """Job with salary='' should pass (empty guard)."""
        jobs = [make_job(salary="")]
        passed, rejected = self.filter_by_salary(jobs, min_salary_monthly=30000)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_salary_below_minimum_rejected(self):
        """Job with salary='25,000/month' and min=30000 should be rejected."""
        jobs = [make_job(salary="25,000/month")]
        passed, rejected = self.filter_by_salary(jobs, min_salary_monthly=30000)
        assert len(passed) == 0
        assert len(rejected) == 1

    def test_salary_above_minimum_passes(self):
        """Job with salary='35,000/month' and min=30000 should pass."""
        jobs = [make_job(salary="35,000/month")]
        passed, rejected = self.filter_by_salary(jobs, min_salary_monthly=30000)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_watchlist_bypass_salary_filter(self):
        """Job with salary='20K/mo', min=30000, but watchlist_match=True should pass (per D-09)."""
        jobs = [make_job(salary="20K/mo", watchlist_match=True)]
        passed, rejected = self.filter_by_salary(jobs, min_salary_monthly=30000)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_non_watchlist_low_salary_rejected(self):
        """Job with salary='20K/mo', min=30000, watchlist_match=False should be rejected."""
        jobs = [make_job(salary="20K/mo", watchlist_match=False)]
        passed, rejected = self.filter_by_salary(jobs, min_salary_monthly=30000)
        assert len(passed) == 0
        assert len(rejected) == 1

    def test_unparseable_salary_passes(self):
        """Job with salary='competitive' (unparseable) should pass (treat as missing)."""
        jobs = [make_job(salary="competitive")]
        passed, rejected = self.filter_by_salary(jobs, min_salary_monthly=30000)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_rejected_job_produces_debug_log(self, caplog):
        """Rejected job produces debug log containing 'salary below minimum' (per D-12)."""
        jobs = [make_job(salary="25,000/month", title="Test Job", company="TestCo")]
        with caplog.at_level(logging.DEBUG, logger="src.filters.salary"):
            self.filter_by_salary(jobs, min_salary_monthly=30000)
        assert any("salary below minimum" in record.message for record in caplog.records)


# ===========================================================================
# Pipeline with Salary Tests
# ===========================================================================


class TestPipelineWithSalary:
    """Tests for pipeline integration with salary filter.

    Verifies salary_rejected in stats, D-13 log format, and D-09 end-to-end.
    """

    @pytest.fixture
    def full_config(self):
        """Config dict with all filter settings for pipeline tests."""
        return {
            "filters": {
                "location_aliases": DEFAULT_LOCATION_ALIASES,
                "remote_keywords": DEFAULT_REMOTE_KEYWORDS,
                "min_salary_monthly": 30000,
            },
            "companies": {
                "blocklist": ["TCS"],
                "watchlist": ["Google"],
            },
        }

    def test_pipeline_stats_include_salary_rejected(self, full_config):
        """Pipeline stats dict includes 'salary_rejected' key with integer value."""
        jobs = [
            make_job(job_id="1", location="Bengaluru, Karnataka, India", salary="20K/mo"),
        ]
        result = run_filter_pipeline(jobs, full_config)
        assert "salary_rejected" in result.stats
        assert isinstance(result.stats["salary_rejected"], int)
        assert result.stats["salary_rejected"] == 1

    def test_pipeline_info_log_includes_salary_count(self, full_config, caplog):
        """Pipeline INFO summary log includes salary count per D-13."""
        jobs = [
            make_job(job_id="1", location="Bengaluru, Karnataka, India", salary="50K/mo"),
        ]
        with caplog.at_level(logging.INFO, logger="src.filters.pipeline"):
            run_filter_pipeline(jobs, full_config)
        # The log should match format: "Filtered: %d -> %d (%d location, %d company, %d salary, %d watchlist)"
        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("salary" in msg for msg in info_messages), (
            f"Expected 'salary' in INFO log messages, got: {info_messages}"
        )

    def test_watchlist_job_with_low_salary_passes_pipeline(self, full_config):
        """Watchlist-matched job with salary '20K/mo' passes full pipeline (D-09 end-to-end)."""
        jobs = [
            make_job(
                job_id="1",
                location="Bengaluru, Karnataka, India",
                company="Google India",
                salary="20K/mo",
            ),
        ]
        result = run_filter_pipeline(jobs, full_config)
        assert len(result.passed) == 1
        assert result.passed[0].watchlist_match is True

    def test_non_watchlist_job_with_low_salary_rejected_by_pipeline(self, full_config):
        """Non-watchlist job with salary '20K/mo' is rejected by the full pipeline."""
        jobs = [
            make_job(
                job_id="1",
                location="Bengaluru, Karnataka, India",
                company="RandomCorp",
                salary="20K/mo",
            ),
        ]
        result = run_filter_pipeline(jobs, full_config)
        assert len(result.passed) == 0
        assert result.stats["salary_rejected"] == 1
