"""Tests for the scheduling module -- run tracking, catch-up, health monitoring, status.

Verifies:
- CONF-04: Catch-up detection when last run >24h ago
- NOTF-03: Health alert after 2+ consecutive scrape_error days
- D-06: Run tracking with explicit status taxonomy
- D-10: Consecutive failure counting (scrape_error only, NOT zero_results)
- D-12: Health alert sent once per streak, reset on non-error completion
- D-13: --status CLI with graceful degradation
"""

import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


class TestRunTracking:
    """Tests for record_run_start and record_run_complete."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    def test_record_run_start_inserts_row(self):
        """record_run_start inserts row with started_at=now(UTC), status='running'."""
        from src.scheduling import record_run_start
        from src.storage.database import get_connection, init_db

        record_run_start("run-001")

        with get_connection() as conn:
            init_db(conn)
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", ("run-001",)
            ).fetchone()

        assert row is not None
        assert row["status"] == "running"
        assert row["started_at"] is not None
        assert row["completed_at"] is None
        assert row["jobs_found"] == 0
        assert row["jobs_notified"] == 0

    def test_record_run_complete_updates_status_success(self):
        """record_run_complete updates row: completed_at set, status='success'."""
        from src.scheduling import record_run_start, record_run_complete, SUCCESS
        from src.storage.database import get_connection, init_db

        record_run_start("run-002")
        record_run_complete("run-002", status=SUCCESS, jobs_found=10, jobs_notified=5)

        with get_connection() as conn:
            init_db(conn)
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", ("run-002",)
            ).fetchone()

        assert row["status"] == "success"
        assert row["completed_at"] is not None
        assert row["jobs_found"] == 10
        assert row["jobs_notified"] == 5

    def test_record_run_complete_zero_results_status(self):
        """record_run_complete with ZERO_RESULTS status."""
        from src.scheduling import record_run_start, record_run_complete, ZERO_RESULTS
        from src.storage.database import get_connection, init_db

        record_run_start("run-003")
        record_run_complete("run-003", status=ZERO_RESULTS, jobs_found=5, jobs_notified=0)

        with get_connection() as conn:
            init_db(conn)
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", ("run-003",)
            ).fetchone()

        assert row["status"] == "zero_results"

    def test_record_run_complete_scrape_error_status(self):
        """record_run_complete with SCRAPE_ERROR status."""
        from src.scheduling import record_run_start, record_run_complete, SCRAPE_ERROR
        from src.storage.database import get_connection, init_db

        record_run_start("run-004")
        record_run_complete("run-004", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        with get_connection() as conn:
            init_db(conn)
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", ("run-004",)
            ).fetchone()

        assert row["status"] == "scrape_error"

    def test_record_run_complete_pipeline_error_status(self):
        """record_run_complete with PIPELINE_ERROR status."""
        from src.scheduling import record_run_start, record_run_complete, PIPELINE_ERROR
        from src.storage.database import get_connection, init_db

        record_run_start("run-005")
        record_run_complete("run-005", status=PIPELINE_ERROR, jobs_found=0, jobs_notified=0)

        with get_connection() as conn:
            init_db(conn)
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", ("run-005",)
            ).fetchone()

        assert row["status"] == "pipeline_error"

    def test_record_run_complete_no_matching_row_no_crash(self):
        """record_run_complete with run_id that has no matching row does NOT crash."""
        from src.scheduling import record_run_complete, SUCCESS

        # Should not raise any exception
        record_run_complete("nonexistent-run", status=SUCCESS, jobs_found=0, jobs_notified=0)


class TestConsecutiveFailures:
    """Tests for get_consecutive_failures counting logic."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    def test_no_runs_returns_zero(self):
        """get_consecutive_failures returns 0 when no runs exist (first-run edge case)."""
        from src.scheduling import get_consecutive_failures

        assert get_consecutive_failures() == 0

    def test_last_run_success_returns_zero(self):
        """get_consecutive_failures returns 0 when last completed run is success."""
        from src.scheduling import record_run_start, record_run_complete, get_consecutive_failures, SUCCESS

        record_run_start("run-1")
        record_run_complete("run-1", status=SUCCESS, jobs_found=5, jobs_notified=3)

        assert get_consecutive_failures() == 0

    def test_last_run_zero_results_returns_zero(self):
        """get_consecutive_failures returns 0 when last completed run is zero_results."""
        from src.scheduling import record_run_start, record_run_complete, get_consecutive_failures, ZERO_RESULTS

        record_run_start("run-1")
        record_run_complete("run-1", status=ZERO_RESULTS, jobs_found=5, jobs_notified=0)

        assert get_consecutive_failures() == 0

    def test_two_scrape_errors_returns_two(self):
        """get_consecutive_failures returns 2 when last 2 completed runs are scrape_error."""
        from src.scheduling import record_run_start, record_run_complete, get_consecutive_failures, SCRAPE_ERROR

        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        assert get_consecutive_failures() == 2

    def test_three_scrape_errors_with_success_before(self):
        """get_consecutive_failures returns 3 when last 3 are scrape_error but success before them."""
        from src.scheduling import (
            record_run_start, record_run_complete, get_consecutive_failures,
            SUCCESS, SCRAPE_ERROR,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SUCCESS, jobs_found=5, jobs_notified=3)
        record_run_start("run-2")
        record_run_complete("run-2", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-3")
        record_run_complete("run-3", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-4")
        record_run_complete("run-4", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        assert get_consecutive_failures() == 3

    def test_pipeline_error_rows_ignored(self):
        """get_consecutive_failures ignores rows with status='pipeline_error'."""
        from src.scheduling import (
            record_run_start, record_run_complete, get_consecutive_failures,
            SCRAPE_ERROR, PIPELINE_ERROR,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=PIPELINE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-3")
        record_run_complete("run-3", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        # pipeline_error is ignored; the two scrape_errors are consecutive
        assert get_consecutive_failures() == 2

    def test_running_status_rows_ignored(self):
        """get_consecutive_failures ignores rows with status='running'."""
        from src.scheduling import (
            record_run_start, record_run_complete, get_consecutive_failures,
            SCRAPE_ERROR,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        # run-2 never completes (still 'running')
        record_run_start("run-2")
        record_run_start("run-3")
        record_run_complete("run-3", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        # 'running' rows are ignored; the two scrape_errors are consecutive
        assert get_consecutive_failures() == 2

    def test_zero_results_does_not_count_as_failure(self):
        """zero_results does NOT count as failure -- only scrape_error does."""
        from src.scheduling import (
            record_run_start, record_run_complete, get_consecutive_failures,
            SCRAPE_ERROR, ZERO_RESULTS,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=ZERO_RESULTS, jobs_found=5, jobs_notified=0)
        record_run_start("run-3")
        record_run_complete("run-3", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        # zero_results breaks the streak -- only 1 consecutive scrape_error
        assert get_consecutive_failures() == 1


class TestCatchup:
    """Tests for check_catchup detection logic."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    def test_first_run_empty_table_logs_first_run(self, caplog):
        """check_catchup logs 'First run -- no previous history' when no completed runs exist."""
        import logging
        from src.scheduling import check_catchup

        with caplog.at_level(logging.INFO):
            check_catchup()

        assert "First run" in caplog.text
        assert "no previous history" in caplog.text

    def test_last_run_over_24h_ago_logs_catchup(self, caplog, monkeypatch):
        """check_catchup logs catch-up message when last completed run >24h ago."""
        import logging
        from src.scheduling import (
            record_run_start, record_run_complete, check_catchup, SUCCESS,
        )
        from src.storage.database import get_connection, init_db

        # Insert a run with completed_at set to 30 hours ago
        record_run_start("old-run")
        record_run_complete("old-run", status=SUCCESS, jobs_found=5, jobs_notified=3)

        # Manually backdate completed_at
        old_time = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        with get_connection() as conn:
            init_db(conn)
            conn.execute(
                "UPDATE runs SET completed_at = ? WHERE run_id = ?",
                (old_time, "old-run"),
            )

        with caplog.at_level(logging.INFO):
            check_catchup()

        assert "Catch-up run triggered" in caplog.text

    def test_last_run_under_24h_ago_no_log(self, caplog):
        """check_catchup does NOT log catch-up when last completed run <24h ago."""
        import logging
        from src.scheduling import (
            record_run_start, record_run_complete, check_catchup, SUCCESS,
        )

        # Just completed a run -- should be less than 24h ago
        record_run_start("recent-run")
        record_run_complete("recent-run", status=SUCCESS, jobs_found=5, jobs_notified=3)

        with caplog.at_level(logging.INFO):
            check_catchup()

        assert "Catch-up" not in caplog.text
        assert "First run" not in caplog.text


class TestHealthMonitoring:
    """Tests for check_health alert logic."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    @pytest.fixture
    def mock_send_email(self):
        """Mock send_email for health alert tests."""
        with patch("src.scheduling.health.send_email") as mock:
            yield mock

    def test_two_scrape_errors_triggers_alert(self, mock_send_email, sample_config):
        """check_health calls send_email when consecutive scrape_error >= 2."""
        from src.scheduling import (
            record_run_start, record_run_complete, check_health, SCRAPE_ERROR,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        check_health(sample_config)

        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args
        assert "Health Alert" in call_args[0][1]  # subject

    def test_one_scrape_error_no_alert(self, mock_send_email, sample_config):
        """check_health does NOT send email when consecutive_failures < 2."""
        from src.scheduling import (
            record_run_start, record_run_complete, check_health, SCRAPE_ERROR,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        check_health(sample_config)

        mock_send_email.assert_not_called()

    def test_zero_results_does_not_trigger_alert(self, mock_send_email, sample_config):
        """check_health does NOT send email when status is zero_results (normal day)."""
        from src.scheduling import (
            record_run_start, record_run_complete, check_health, ZERO_RESULTS,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=ZERO_RESULTS, jobs_found=5, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=ZERO_RESULTS, jobs_found=3, jobs_notified=0)

        check_health(sample_config)

        mock_send_email.assert_not_called()

    def test_alert_sent_once_per_streak(self, mock_send_email, sample_config):
        """check_health does NOT send email when health_alert_sent == 1 (once per streak)."""
        from src.scheduling import (
            record_run_start, record_run_complete, check_health, SCRAPE_ERROR,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        # First call should send
        check_health(sample_config)
        assert mock_send_email.call_count == 1

        # Third failure
        record_run_start("run-3")
        record_run_complete("run-3", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        # Second call should NOT send (alert already sent for this streak)
        check_health(sample_config)
        assert mock_send_email.call_count == 1  # Still 1

    def test_alert_flag_resets_on_success(self, mock_send_email, sample_config):
        """check_health resets health_alert_sent when latest completed run is NOT scrape_error."""
        from src.scheduling import (
            record_run_start, record_run_complete, check_health,
            SCRAPE_ERROR, SUCCESS,
        )

        # First streak: trigger alert
        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        check_health(sample_config)
        assert mock_send_email.call_count == 1

        # Success run -- resets the streak
        record_run_start("run-3")
        record_run_complete("run-3", status=SUCCESS, jobs_found=5, jobs_notified=3)
        check_health(sample_config)

        # New streak of failures
        record_run_start("run-4")
        record_run_complete("run-4", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-5")
        record_run_complete("run-5", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        # Should send again (flag was reset by success)
        check_health(sample_config)
        assert mock_send_email.call_count == 2

    def test_alert_flag_resets_on_zero_results(self, mock_send_email, sample_config):
        """check_health resets health_alert_sent when zero_results (also non-error)."""
        from src.scheduling import (
            record_run_start, record_run_complete, check_health,
            SCRAPE_ERROR, ZERO_RESULTS,
        )

        # First streak
        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        check_health(sample_config)
        assert mock_send_email.call_count == 1

        # zero_results clears the streak
        record_run_start("run-3")
        record_run_complete("run-3", status=ZERO_RESULTS, jobs_found=5, jobs_notified=0)
        check_health(sample_config)

        # New streak
        record_run_start("run-4")
        record_run_complete("run-4", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-5")
        record_run_complete("run-5", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        check_health(sample_config)
        assert mock_send_email.call_count == 2

    def test_health_alert_subject_format(self, mock_send_email, sample_config):
        """Health alert subject matches expected format."""
        from src.scheduling import (
            record_run_start, record_run_complete, check_health, SCRAPE_ERROR,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)
        record_run_start("run-2")
        record_run_complete("run-2", status=SCRAPE_ERROR, jobs_found=0, jobs_notified=0)

        check_health(sample_config)

        call_args = mock_send_email.call_args
        subject = call_args[0][1]
        assert "LinkedInScript: Health Alert" in subject
        assert "2 consecutive days with zero results" in subject


class TestStatus:
    """Tests for print_status and get_last_run_time."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    def test_get_last_run_time_no_runs(self):
        """get_last_run_time returns None when no completed runs exist."""
        from src.scheduling import get_last_run_time

        assert get_last_run_time() is None

    def test_get_last_run_time_returns_timestamp(self):
        """get_last_run_time returns ISO timestamp of most recent completed run."""
        from src.scheduling import (
            record_run_start, record_run_complete, get_last_run_time, SUCCESS,
        )

        record_run_start("run-1")
        record_run_complete("run-1", status=SUCCESS, jobs_found=5, jobs_notified=3)

        result = get_last_run_time()
        assert result is not None
        # Should be a valid ISO timestamp
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None or "+" in result or "Z" in result

    def test_print_status_outputs_db_info_when_subprocess_fails(self, capsys, sample_config):
        """print_status prints DB info even when PowerShell subprocess fails."""
        from src.scheduling import print_status

        with patch("subprocess.run", side_effect=FileNotFoundError("No powershell")):
            print_status(sample_config)

        output = capsys.readouterr().out
        # Should show last run info and failure count (from DB)
        assert "Last run" in output or "[1/3]" in output
        assert "failure" in output.lower() or "[2/3]" in output
        # Should show graceful degradation message for scheduler
        assert "Not available" in output or "Not scheduled" in output

    def test_print_status_shows_not_scheduled_when_task_not_found(self, capsys, sample_config):
        """print_status shows 'Not scheduled' when Task Scheduler task doesn't exist."""
        from src.scheduling import print_status

        mock_result = MagicMock()
        mock_result.stdout = "Not scheduled"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            print_status(sample_config)

        output = capsys.readouterr().out
        assert "Not scheduled" in output

    def test_print_status_handles_timeout(self, capsys, sample_config):
        """print_status handles subprocess timeout gracefully (T-05-02)."""
        from src.scheduling import print_status

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
            print_status(sample_config)

        output = capsys.readouterr().out
        # Should still output DB-derived info
        assert "Last run" in output or "[1/3]" in output
        # Graceful degradation for scheduler query
        assert "Not available" in output or "Not scheduled" in output
