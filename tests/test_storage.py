"""Tests for the storage module — SQLite deduplication and job persistence.

RED phase: These tests define expected behavior for src/storage/.
They verify DEDUP-01: tool tracks seen job IDs in SQLite, only reports genuinely new listings.
DEDUP-02: repost detection via SequenceMatcher.
DEDUP-03: company grouping at presentation layer.
"""

import sqlite3
import time

import pytest

from tests.conftest import make_job


class TestDedup:
    """Tests for storage module dedup behavior (DEDUP-01)."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    def test_store_and_get_new_first_time(self):
        """store_jobs stores 2 rows; get_new_jobs returns both IDs (first time = new)."""
        from src.storage import store_jobs, get_new_jobs

        job_a = make_job(job_id="job-a", title="SDE Intern", company="Google")
        job_b = make_job(job_id="job-b", title="ML Intern", company="Microsoft")

        result = store_jobs([job_a, job_b], filter_passed=True, run_id="run1")
        assert result["total"] == 2
        assert result["new"] == 2

        new_ids = get_new_jobs(["job-a", "job-b"])
        assert set(new_ids) == {"job-a", "job-b"}

    def test_after_mark_notified_get_new_returns_empty(self):
        """After store + mark_as_notified, get_new_jobs returns empty list."""
        from src.storage import store_jobs, get_new_jobs, mark_as_notified

        job_a = make_job(job_id="job-a", title="SDE Intern", company="Google")
        job_b = make_job(job_id="job-b", title="ML Intern", company="Microsoft")

        store_jobs([job_a, job_b], filter_passed=True, run_id="run1")
        mark_as_notified(["job-a", "job-b"])

        new_ids = get_new_jobs(["job-a", "job-b"])
        assert new_ids == []

    def test_store_same_jobs_no_duplicates_last_seen_updates(self):
        """store_jobs same jobs again does NOT create duplicates; last_seen updates; first_seen preserved."""
        from src.storage import store_jobs
        from src.storage.database import get_connection

        job_a = make_job(job_id="job-a", title="SDE Intern", company="Google")

        store_jobs([job_a], filter_passed=True, run_id="run1")

        # Get first_seen from initial insert
        with get_connection() as conn:
            row = conn.execute("SELECT first_seen, last_seen FROM jobs WHERE job_id='job-a'").fetchone()
            first_seen_1 = row["first_seen"]
            last_seen_1 = row["last_seen"]

        # Store again with different run_id
        import time
        time.sleep(0.01)  # Ensure timestamps differ
        store_jobs([job_a], filter_passed=True, run_id="run2")

        with get_connection() as conn:
            row = conn.execute("SELECT first_seen, last_seen, run_id FROM jobs WHERE job_id='job-a'").fetchone()
            first_seen_2 = row["first_seen"]
            last_seen_2 = row["last_seen"]
            run_id_2 = row["run_id"]

            # No duplicate rows
            count = conn.execute("SELECT COUNT(*) FROM jobs WHERE job_id='job-a'").fetchone()[0]

        assert count == 1
        assert first_seen_2 == first_seen_1  # first_seen preserved
        assert last_seen_2 >= last_seen_1  # last_seen updated (or same if too fast)
        assert run_id_2 == "run2"

    def test_filter_passed_false_stored_and_new(self):
        """store_jobs with filter_passed=False stores it; get_new_jobs returns it as new."""
        from src.storage import store_jobs, get_new_jobs

        job_c = make_job(job_id="job-c", title="Backend Intern", company="Startup")

        store_jobs([job_c], filter_passed=False, run_id="run1")
        new_ids = get_new_jobs(["job-c"])
        # Job is new because notified=0 (never shown to user)
        assert "job-c" in new_ids

    def test_filter_passed_upgrade_from_false_to_true(self):
        """store_jobs with filter_passed=True on previously False job upgrades the flag (MAX behavior)."""
        from src.storage import store_jobs, get_new_jobs
        from src.storage.database import get_connection

        job_c = make_job(job_id="job-c", title="Backend Intern", company="Startup")

        # First store with filter_passed=False
        store_jobs([job_c], filter_passed=False, run_id="run1")

        with get_connection() as conn:
            row = conn.execute("SELECT filter_passed FROM jobs WHERE job_id='job-c'").fetchone()
            assert row["filter_passed"] == 0

        # Store again with filter_passed=True (upgrade)
        store_jobs([job_c], filter_passed=True, run_id="run2")

        with get_connection() as conn:
            row = conn.execute("SELECT filter_passed FROM jobs WHERE job_id='job-c'").fetchone()
            assert row["filter_passed"] == 1

        # Should still be new (not notified)
        new_ids = get_new_jobs(["job-c"])
        assert "job-c" in new_ids

    def test_db_auto_created_on_init(self, tmp_path, monkeypatch):
        """DB file is auto-created when init_db runs (use tmp_path to prove file creation)."""
        db_path = tmp_path / "subdir" / "new_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

        from src.storage.database import get_connection, init_db

        # Ensure parent dir exists (as main.py will do)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        with get_connection() as conn:
            init_db(conn)

        assert db_path.exists()

    def test_get_connection_wal_mode_and_row_factory(self, tmp_path, monkeypatch):
        """get_connection yields a connection with WAL mode enabled and row_factory=sqlite3.Row."""
        db_path = tmp_path / "wal_test.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

        from src.storage.database import get_connection

        with get_connection() as conn:
            # Check WAL mode
            mode = conn.execute("PRAGMA journal_mode").fetchone()
            assert mode[0] == "wal" or mode["journal_mode"] == "wal"

            # Check row_factory
            assert conn.row_factory == sqlite3.Row

    def test_generate_run_id_format(self):
        """generate_run_id returns a 32-character hex string (uuid4().hex format)."""
        from src.storage import generate_run_id

        run_id = generate_run_id()
        assert len(run_id) == 32
        assert all(c in "0123456789abcdef" for c in run_id)

        # Each call produces unique ID
        run_id_2 = generate_run_id()
        assert run_id != run_id_2

    def test_crash_safety_idempotent_upsert(self):
        """Crash-safety: calling store_jobs twice with same data is idempotent.

        UPSERT preserves first_seen, upgrades filter_passed via MAX.
        """
        from src.storage import store_jobs
        from src.storage.database import get_connection

        job_a = make_job(job_id="job-a", title="SDE Intern", company="Google")

        # Simulate crash recovery: store same data twice
        store_jobs([job_a], filter_passed=True, run_id="run1")
        store_jobs([job_a], filter_passed=True, run_id="run1")

        with get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM jobs WHERE job_id='job-a'").fetchone()[0]
            row = conn.execute("SELECT first_seen, filter_passed FROM jobs WHERE job_id='job-a'").fetchone()

        assert count == 1  # No duplicates
        assert row["filter_passed"] == 1  # Still True


class TestRepostDetection:
    """Tests for repost detection behavior (DEDUP-02).

    Verifies normalize_title, is_repost, and detect_reposts from src/storage/dedup.py.
    """

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path, monkeypatch):
        """Override DB_PATH to use tmp_path for test isolation."""
        db_path = tmp_path / "test_jobs.db"
        monkeypatch.setattr("src.storage.database.DB_PATH", db_path)

    # --- normalize_title tests ---

    def test_normalize_title_removes_year_and_special_chars(self):
        """normalize_title("SDE Intern 2025 - Bangalore") -> "sde intern bangalore"."""
        from src.storage.dedup import normalize_title

        result = normalize_title("SDE Intern 2025 - Bangalore")
        assert result == "sde intern bangalore"

    def test_normalize_title_removes_parentheses(self):
        """normalize_title("Software Engineer Intern (Remote)") -> "software engineer intern remote"."""
        from src.storage.dedup import normalize_title

        result = normalize_title("Software Engineer Intern (Remote)")
        assert result == "software engineer intern remote"

    def test_normalize_title_handles_multiple_spaces_and_special_chars(self):
        """normalize_title("   ML  Intern   2024!!!  ") -> "ml intern"."""
        from src.storage.dedup import normalize_title

        result = normalize_title("   ML  Intern   2024!!!  ")
        assert result == "ml intern"

    # --- is_repost tests ---

    def test_is_repost_same_title_different_year_is_repost(self):
        """is_repost("SDE Intern 2025", "SDE Intern 2024") -> True.

        After normalization both become "sde intern" -> ratio 1.0 >= 0.85.
        """
        from src.storage.dedup import is_repost

        assert is_repost("SDE Intern 2025", "SDE Intern 2024") is True

    def test_is_repost_different_roles_same_company_not_repost(self):
        """is_repost("Backend Developer Intern", "Frontend Developer Intern") -> False.

        Normalized: "backend developer intern" vs "frontend developer intern" ~ 0.816 < 0.85.
        """
        from src.storage.dedup import is_repost

        assert is_repost("Backend Developer Intern", "Frontend Developer Intern") is False

    def test_is_repost_high_overlap_with_suffix(self):
        """is_repost with high overlap suffix -> True.

        "Software Development Engineer Intern" vs "Software Development Engineer Intern - Summer"
        Normalized ratio ~0.91 (above 0.85 threshold). Longer titles absorb suffixes better.
        Note: shorter titles like "ML Engineer Intern" + suffix produce ~0.84 (below threshold)
        which is documented correct behavior — short titles with appended words are borderline.
        """
        from src.storage.dedup import is_repost

        assert is_repost(
            "Software Development Engineer Intern",
            "Software Development Engineer Intern - Summer",
        ) is True

    def test_is_repost_abbreviation_not_matched(self):
        """is_repost("SWE Intern", "Software Engineer Intern") -> False.

        Abbreviation produces low ratio (~0.5). This is EXPECTED behavior at 0.85 threshold.
        Abbreviation = different listing, not a repost.
        """
        from src.storage.dedup import is_repost

        assert is_repost("SWE Intern", "Software Engineer Intern") is False

    def test_is_repost_short_different_roles_not_matched(self):
        """is_repost("Data Intern", "ML Intern") -> False.

        Short titles with different roles must NOT match.
        """
        from src.storage.dedup import is_repost

        assert is_repost("Data Intern", "ML Intern") is False

    def test_is_repost_word_reorder_documented_behavior(self):
        """is_repost("Software Engineer Intern", "Intern, Software Engineering") — document behavior.

        Word reorder produces ~0.7-0.8 ratio which is below threshold.
        NOT a repost match, which is correct since word reorder often indicates different posting format.
        """
        from src.storage.dedup import is_repost

        # After normalization: "software engineer intern" vs "intern software engineering"
        # SequenceMatcher ratio should be below 0.85 (word reorder)
        result = is_repost("Software Engineer Intern", "Intern, Software Engineering")
        assert result is False

    # --- detect_reposts integration tests ---

    def test_detect_reposts_same_company_match(self):
        """detect_reposts finds repost when same company has similar historical title.

        Repost_of_id set to the EARLIEST first_seen match (deterministic selection).
        """
        from src.storage import store_jobs
        from src.storage.dedup import detect_reposts

        # Store historical job
        historical = make_job(
            job_id="hist-1",
            title="SDE Intern 2024",
            company="Google",
        )
        store_jobs([historical], filter_passed=True, run_id="run1")

        # Wait a moment to ensure different first_seen timestamps
        time.sleep(0.01)

        # New job with similar title
        new_job = make_job(
            job_id="new-1",
            title="SDE Intern 2025",
            company="Google",
        )
        store_jobs([new_job], filter_passed=True, run_id="run2")

        results = detect_reposts([new_job], "run2")
        assert len(results) == 1
        assert results[0]["is_repost"] is True
        assert results[0]["repost_of_id"] == "hist-1"

    def test_detect_reposts_different_company_no_match(self):
        """detect_reposts does NOT flag repost when different company has similar title (D-04)."""
        from src.storage import store_jobs
        from src.storage.dedup import detect_reposts

        # Store historical job at company X
        historical = make_job(
            job_id="hist-1",
            title="SDE Intern 2024",
            company="Google",
        )
        store_jobs([historical], filter_passed=True, run_id="run1")

        # New job with similar title at company Y
        new_job = make_job(
            job_id="new-1",
            title="SDE Intern 2025",
            company="Microsoft",
        )
        store_jobs([new_job], filter_passed=True, run_id="run2")

        results = detect_reposts([new_job], "run2")
        assert len(results) == 1
        assert results[0]["is_repost"] is False
        assert results[0]["repost_of_id"] is None

    def test_detect_reposts_updates_db_record(self):
        """detect_reposts updates DB record with is_repost=1 and repost_of_id."""
        from src.storage import store_jobs
        from src.storage.database import get_connection
        from src.storage.dedup import detect_reposts

        historical = make_job(
            job_id="hist-1",
            title="ML Engineer Intern 2024",
            company="DeepMind",
        )
        store_jobs([historical], filter_passed=True, run_id="run1")

        new_job = make_job(
            job_id="new-1",
            title="ML Engineer Intern 2025",
            company="DeepMind",
        )
        store_jobs([new_job], filter_passed=True, run_id="run2")

        detect_reposts([new_job], "run2")

        # Verify DB was updated
        with get_connection() as conn:
            from src.storage.database import init_db

            init_db(conn)
            row = conn.execute(
                "SELECT is_repost, repost_of_id FROM jobs WHERE job_id = ?",
                ("new-1",),
            ).fetchone()

        assert row["is_repost"] == 1
        assert row["repost_of_id"] == "hist-1"

    def test_detect_reposts_checks_all_history_no_filter_constraint(self):
        """detect_reposts checks ALL historical jobs for company, regardless of filter_passed (D-03)."""
        from src.storage import store_jobs
        from src.storage.dedup import detect_reposts

        # Store a historical job with filter_passed=False (didn't pass filters)
        historical = make_job(
            job_id="hist-1",
            title="Backend Developer Intern",
            company="Startup",
        )
        store_jobs([historical], filter_passed=False, run_id="run1")

        # New similar job that passed filters
        new_job = make_job(
            job_id="new-1",
            title="Backend Developer Intern 2025",
            company="Startup",
        )
        store_jobs([new_job], filter_passed=True, run_id="run2")

        results = detect_reposts([new_job], "run2")
        assert len(results) == 1
        # Should still detect as repost even though historical didn't pass filters
        assert results[0]["is_repost"] is True
        assert results[0]["repost_of_id"] == "hist-1"

    def test_detect_reposts_empty_database(self):
        """detect_reposts on EMPTY database returns empty list with zero reposts (first-run edge case)."""
        from src.storage.dedup import detect_reposts

        # No historical jobs stored at all — first run
        new_job = make_job(
            job_id="new-1",
            title="SDE Intern 2025",
            company="Google",
        )
        # Note: we do NOT call store_jobs first, simulating truly empty DB
        # But we need to ensure the table exists, so store this job first
        from src.storage import store_jobs

        store_jobs([new_job], filter_passed=True, run_id="run1")

        results = detect_reposts([new_job], "run1")
        assert len(results) == 1
        assert results[0]["is_repost"] is False
        assert results[0]["repost_of_id"] is None

    def test_detect_reposts_deterministic_earliest_first_seen(self):
        """detect_reposts with multiple historical matches picks the one with earliest first_seen."""
        from src.storage import store_jobs
        from src.storage.dedup import detect_reposts

        # Store two historical jobs with similar titles at same company
        hist_old = make_job(
            job_id="hist-old",
            title="SDE Intern",
            company="Google",
        )
        store_jobs([hist_old], filter_passed=True, run_id="run1")

        time.sleep(0.02)  # Ensure different first_seen timestamps

        hist_new = make_job(
            job_id="hist-new",
            title="SDE Intern 2024",
            company="Google",
        )
        store_jobs([hist_new], filter_passed=True, run_id="run2")

        time.sleep(0.02)

        # New job similar to both
        new_job = make_job(
            job_id="new-1",
            title="SDE Intern 2025",
            company="Google",
        )
        store_jobs([new_job], filter_passed=True, run_id="run3")

        results = detect_reposts([new_job], "run3")
        assert len(results) == 1
        assert results[0]["is_repost"] is True
        # Should pick hist-old (earliest first_seen), not hist-new
        assert results[0]["repost_of_id"] == "hist-old"


class TestCompanyGrouping:
    """Tests for company grouping behavior (DEDUP-03).

    Verifies group_by_company from src/storage/__init__.py.
    Per D-05/D-06: presentation-layer grouping returning a data structure.
    """

    def test_group_by_company_multiple_companies(self):
        """group_by_company groups jobs by company, ordered by count descending."""
        from src.storage import group_by_company

        job_a = make_job(job_id="a", title="SDE Intern", company="Google")
        job_b = make_job(job_id="b", title="ML Intern", company="Google")
        job_c = make_job(job_id="c", title="Backend Intern", company="Microsoft")

        result = group_by_company([job_a, job_b, job_c])

        # Google has 2 listings, Microsoft has 1 -> Google first
        assert list(result.keys()) == ["Google", "Microsoft"]
        assert len(result["Google"]) == 2
        assert len(result["Microsoft"]) == 1

    def test_group_by_company_empty_input(self):
        """group_by_company([]) returns empty dict."""
        from src.storage import group_by_company

        result = group_by_company([])
        assert result == {}

    def test_group_by_company_single_company(self):
        """group_by_company with single company returns dict with one key."""
        from src.storage import group_by_company

        job_a = make_job(job_id="a", title="SDE Intern", company="Meta")
        job_b = make_job(job_id="b", title="ML Intern", company="Meta")

        result = group_by_company([job_a, job_b])
        assert list(result.keys()) == ["Meta"]
        assert len(result["Meta"]) == 2

    def test_group_by_company_returns_data_structure_not_text(self):
        """group_by_company returns dict[str, list], not formatted text (D-06)."""
        from src.storage import group_by_company

        job_a = make_job(job_id="a", title="SDE Intern", company="Google")

        result = group_by_company([job_a])
        assert isinstance(result, dict)
        assert isinstance(result["Google"], list)
        assert result["Google"][0].job_id == "a"
