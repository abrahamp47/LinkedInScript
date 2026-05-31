"""Tests for database retention purge behavior.

RED phase: These tests define expected behavior for purge_old_entries in src/storage/database.py.
They verify:
- D-11: Purge entries from both jobs and runs tables when older than 90 days
- D-12: Run the purge at pipeline start (after init_db, before scraping)
- D-13: Hard delete (no soft-delete)
- D-14: Log the purge count only when > 0
- D-15: Retention period configurable via config.yaml database.retention_days: 90
- Review item 1: idx_jobs_first_seen confirmed in schema
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import make_job


class TestRetentionPurge:
    """Tests for purge_old_entries function (D-11 through D-15)."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    def _insert_job(self, conn, job_id: str, first_seen: str):
        """Helper to insert a job directly with a specific first_seen timestamp."""
        conn.execute(
            """INSERT INTO jobs (job_id, title, company, first_seen, last_seen, run_id)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (job_id, "Test Job", "TestCo", first_seen, first_seen, "run-test"),
        )

    def _insert_run(self, conn, run_id: str, started_at: str):
        """Helper to insert a run directly with a specific started_at timestamp."""
        conn.execute(
            """INSERT INTO runs (run_id, started_at, status)
            VALUES (?, ?, ?)""",
            (run_id, started_at, "success"),
        )

    def test_purge_deletes_old_jobs_and_runs(self):
        """purge_old_entries(90) deletes jobs with first_seen older than 90 days and runs with started_at older than 90 days."""
        from src.storage.database import get_connection, init_db, purge_old_entries

        old_ts = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        with get_connection() as conn:
            init_db(conn)
            self._insert_job(conn, "old-job", old_ts)
            self._insert_job(conn, "recent-job", recent_ts)
            self._insert_run(conn, "old-run", old_ts)
            self._insert_run(conn, "recent-run", recent_ts)

        jobs_deleted, runs_deleted = purge_old_entries(retention_days=90)

        assert jobs_deleted == 1
        assert runs_deleted == 1

        # Verify old entries are gone, recent entries remain
        with get_connection() as conn:
            init_db(conn)
            jobs = conn.execute("SELECT job_id FROM jobs").fetchall()
            runs = conn.execute("SELECT run_id FROM runs").fetchall()

        assert len(jobs) == 1
        assert jobs[0]["job_id"] == "recent-job"
        assert len(runs) == 1
        assert runs[0]["run_id"] == "recent-run"

    def test_purge_does_not_delete_within_retention_window(self):
        """purge_old_entries does NOT delete jobs/runs within retention window."""
        from src.storage.database import get_connection, init_db, purge_old_entries

        # All entries are within 90 days
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        with get_connection() as conn:
            init_db(conn)
            self._insert_job(conn, "job-1", recent_ts)
            self._insert_job(conn, "job-2", recent_ts)
            self._insert_run(conn, "run-1", recent_ts)

        jobs_deleted, runs_deleted = purge_old_entries(retention_days=90)

        assert jobs_deleted == 0
        assert runs_deleted == 0

        # All entries remain
        with get_connection() as conn:
            init_db(conn)
            job_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

        assert job_count == 2
        assert run_count == 1

    def test_purge_returns_correct_counts(self):
        """purge_old_entries returns tuple (jobs_deleted, runs_deleted) with correct counts."""
        from src.storage.database import get_connection, init_db, purge_old_entries

        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()

        with get_connection() as conn:
            init_db(conn)
            self._insert_job(conn, "old-1", old_ts)
            self._insert_job(conn, "old-2", old_ts)
            self._insert_job(conn, "old-3", old_ts)
            self._insert_run(conn, "old-run-1", old_ts)
            self._insert_run(conn, "old-run-2", old_ts)

        result = purge_old_entries(retention_days=90)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result == (3, 2)

    def test_purge_empty_database_returns_zeros(self):
        """purge_old_entries with empty database returns (0, 0)."""
        from src.storage.database import get_connection, init_db, purge_old_entries

        # Initialize empty DB
        with get_connection() as conn:
            init_db(conn)

        result = purge_old_entries(retention_days=90)
        assert result == (0, 0)

    def test_purge_default_retention_days_is_90(self):
        """purge_old_entries defaults to 90 days when called without argument."""
        from src.storage.database import get_connection, init_db, purge_old_entries

        # Insert job at exactly 89 days old (should NOT be purged with default 90)
        within_ts = (datetime.now(timezone.utc) - timedelta(days=89)).isoformat()
        # Insert job at exactly 91 days old (should be purged with default 90)
        outside_ts = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()

        with get_connection() as conn:
            init_db(conn)
            self._insert_job(conn, "within", within_ts)
            self._insert_job(conn, "outside", outside_ts)

        jobs_deleted, _ = purge_old_entries()  # No argument = default 90

        assert jobs_deleted == 1

    def test_purge_logs_when_count_greater_than_zero(self, caplog):
        """purge_old_entries logs 'Purged N jobs and M runs older than 90 days' when count > 0."""
        from src.storage.database import get_connection, init_db, purge_old_entries

        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()

        with get_connection() as conn:
            init_db(conn)
            self._insert_job(conn, "old-job", old_ts)
            self._insert_run(conn, "old-run", old_ts)

        with caplog.at_level(logging.INFO, logger="src.storage.database"):
            purge_old_entries(retention_days=90)

        assert "Purged 1 jobs and 1 runs older than 90 days" in caplog.text

    def test_purge_does_not_log_when_counts_are_zero(self, caplog):
        """purge_old_entries does NOT log when both counts are 0."""
        from src.storage.database import get_connection, init_db, purge_old_entries

        # Empty DB
        with get_connection() as conn:
            init_db(conn)

        with caplog.at_level(logging.INFO, logger="src.storage.database"):
            purge_old_entries(retention_days=90)

        assert "Purged" not in caplog.text


class TestIndexes:
    """Tests verifying required database indexes exist in schema."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    def test_idx_jobs_first_seen_exists(self):
        """idx_jobs_first_seen index exists in schema (review item 1 - already present)."""
        from src.storage.database import get_connection, init_db

        with get_connection() as conn:
            init_db(conn)
            indexes = conn.execute("PRAGMA index_list('jobs')").fetchall()
            index_names = [idx["name"] for idx in indexes]

        assert "idx_jobs_first_seen" in index_names

    def test_idx_runs_started_exists(self):
        """idx_runs_started index exists in schema (added for efficient purge on runs)."""
        from src.storage.database import get_connection, init_db

        with get_connection() as conn:
            init_db(conn)
            indexes = conn.execute("PRAGMA index_list('runs')").fetchall()
            index_names = [idx["name"] for idx in indexes]

        assert "idx_runs_started" in index_names
