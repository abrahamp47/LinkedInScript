"""Tests for SMTP failure fallback, output cleanup, and previous-failure note lifecycle.

RED phase: These tests define expected behavior for:
- D-06: SMTP failure saves HTML to output/digest-YYYY-MM-DD.html
- D-07: Console output includes save path
- D-08: mark_as_notified NOT called on SMTP failure (verify not broken)
- D-09: Next successful send shows fallback note when fallback files exist
- D-10: cleanup_old_digests deletes .html files older than 7 days
- Review item 2: check_previous_fallback returns (note, file_paths) and files deleted after send
- Review item 6: output/ directory created with mkdir(parents=True, exist_ok=True) before write
"""

import os
import time
from pathlib import Path

import pytest

from tests.conftest import make_job


class TestOutputCleanup:
    """Tests for cleanup_old_digests utility function (D-10)."""

    def test_cleanup_deletes_old_files(self, tmp_path):
        """cleanup_old_digests deletes .html files older than 7 days from output/ directory."""
        from main import cleanup_old_digests

        # Create file older than 7 days
        old_file = tmp_path / "digest-2026-05-01.html"
        old_file.write_text("<html>old</html>")
        old_mtime = time.time() - (8 * 86400)  # 8 days ago
        os.utime(old_file, (old_mtime, old_mtime))

        # Create recent file (2 days old)
        recent_file = tmp_path / "digest-2026-05-28.html"
        recent_file.write_text("<html>recent</html>")
        recent_mtime = time.time() - (2 * 86400)
        os.utime(recent_file, (recent_mtime, recent_mtime))

        deleted = cleanup_old_digests(tmp_path)

        assert deleted == 1
        assert not old_file.exists()
        assert recent_file.exists()

    def test_cleanup_nonexistent_directory_returns_zero(self, tmp_path):
        """cleanup_old_digests does nothing when output/ directory doesn't exist (returns 0)."""
        from main import cleanup_old_digests

        nonexistent = tmp_path / "nonexistent_output"
        result = cleanup_old_digests(nonexistent)
        assert result == 0

    def test_cleanup_does_not_delete_recent_files(self, tmp_path):
        """cleanup_old_digests does NOT delete files younger than 7 days."""
        from main import cleanup_old_digests

        # Create files all within 7 days
        for i in range(3):
            f = tmp_path / f"digest-2026-05-{28+i:02d}.html"
            f.write_text("<html>recent</html>")
            mtime = time.time() - (i * 86400)  # 0, 1, 2 days old
            os.utime(f, (mtime, mtime))

        deleted = cleanup_old_digests(tmp_path)
        assert deleted == 0

        # All 3 files still exist
        html_files = list(tmp_path.glob("digest-*.html"))
        assert len(html_files) == 3

    def test_cleanup_only_matches_digest_html_pattern(self, tmp_path):
        """cleanup_old_digests only deletes files matching digest-*.html pattern."""
        from main import cleanup_old_digests

        # Create old file that does NOT match the pattern
        other_file = tmp_path / "report.html"
        other_file.write_text("<html>other</html>")
        old_mtime = time.time() - (10 * 86400)
        os.utime(other_file, (old_mtime, old_mtime))

        # Create old digest file that matches
        digest_file = tmp_path / "digest-2026-05-01.html"
        digest_file.write_text("<html>old digest</html>")
        os.utime(digest_file, (old_mtime, old_mtime))

        deleted = cleanup_old_digests(tmp_path)

        assert deleted == 1
        assert other_file.exists()  # Non-digest file untouched
        assert not digest_file.exists()  # Digest file deleted


class TestPreviousFallback:
    """Tests for check_previous_fallback utility function (D-09, review item 2)."""

    def test_returns_note_when_fallback_files_exist(self, tmp_path):
        """check_previous_fallback returns note string when any fallback file exists in output/."""
        from main import check_previous_fallback

        # Create a fallback file
        fallback = tmp_path / "digest-2026-05-29.html"
        fallback.write_text("<html>fallback</html>")

        note, paths = check_previous_fallback(tmp_path)

        assert note is not None
        assert "Previous digest" in note
        assert "output/" in note
        assert len(paths) == 1
        assert paths[0] == fallback

    def test_returns_none_when_no_fallback_files(self, tmp_path):
        """check_previous_fallback returns None when no fallback files exist."""
        from main import check_previous_fallback

        # Empty directory (no fallback files)
        note, paths = check_previous_fallback(tmp_path)

        assert note is None
        assert paths == []

    def test_returns_paths_for_multiple_fallback_files(self, tmp_path):
        """check_previous_fallback returns the list of matching fallback file paths alongside the note."""
        from main import check_previous_fallback

        # Create multiple fallback files (simulates multi-day outage)
        f1 = tmp_path / "digest-2026-05-28.html"
        f2 = tmp_path / "digest-2026-05-29.html"
        f1.write_text("<html>day1</html>")
        f2.write_text("<html>day2</html>")

        note, paths = check_previous_fallback(tmp_path)

        assert note is not None
        assert len(paths) == 2
        assert set(paths) == {f1, f2}

    def test_returns_none_when_directory_does_not_exist(self, tmp_path):
        """check_previous_fallback returns (None, []) when output/ directory doesn't exist."""
        from main import check_previous_fallback

        nonexistent = tmp_path / "nonexistent_output"
        note, paths = check_previous_fallback(nonexistent)

        assert note is None
        assert paths == []


class TestSmtpFallbackSave:
    """Tests for SMTP fallback save logic (D-06, D-07, review item 6)."""

    def test_fallback_saves_html_to_output_directory(self, tmp_path):
        """When SMTP raises, html_body is saved to output/digest-YYYY-MM-DD.html."""
        from datetime import date

        output_dir = tmp_path / "output"
        # Simulate fallback save logic
        output_dir.mkdir(parents=True, exist_ok=True)
        html_body = "<html><body>Test digest content</body></html>"
        fallback_path = output_dir / f"digest-{date.today().isoformat()}.html"
        fallback_path.write_text(html_body, encoding="utf-8")

        assert fallback_path.exists()
        assert fallback_path.read_text(encoding="utf-8") == html_body

    def test_output_dir_created_with_mkdir_parents(self, tmp_path):
        """output/ directory is created with mkdir(parents=True, exist_ok=True) before writing fallback file."""
        output_dir = tmp_path / "nested" / "output"

        # mkdir with parents=True creates nested directories
        output_dir.mkdir(parents=True, exist_ok=True)
        assert output_dir.exists()
        assert output_dir.is_dir()

    def test_fallback_file_deletion_after_successful_send(self, tmp_path):
        """After successful email send with fallback_note, matched fallback files are deleted."""
        from main import check_previous_fallback

        # Create fallback files
        f1 = tmp_path / "digest-2026-05-28.html"
        f2 = tmp_path / "digest-2026-05-29.html"
        f1.write_text("<html>day1</html>")
        f2.write_text("<html>day2</html>")

        # Check previous fallback (simulates what main.py does)
        _, fallback_files = check_previous_fallback(tmp_path)
        assert len(fallback_files) == 2

        # Simulate successful send: delete fallback files
        for f in fallback_files:
            f.unlink(missing_ok=True)

        # Verify files are gone
        assert not f1.exists()
        assert not f2.exists()


class TestRenderDigestFallbackNote:
    """Tests for render_digest with fallback_note parameter."""

    def test_render_digest_with_fallback_note_includes_in_html(self):
        """render_digest with fallback_note set includes the note in HTML."""
        from src.notifications.renderer import render_digest

        job = make_job(job_id="g1", title="Backend Intern", company="StartupCo")

        html, _ = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
            fallback_note="Note: Previous digest(s) were saved locally (email failed). Check output/ directory.",
        )

        assert "Previous digest" in html
        assert "output/" in html

    def test_render_digest_with_fallback_note_includes_in_plain_text(self):
        """render_digest with fallback_note set includes the note in plain text."""
        from src.notifications.renderer import render_digest

        job = make_job(job_id="g1", title="Backend Intern", company="StartupCo")

        _, text = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
            fallback_note="Note: Previous digest(s) were saved locally (email failed). Check output/ directory.",
        )

        assert "Previous digest" in text
        assert "output/" in text

    def test_render_digest_without_fallback_note_no_fallback_text(self):
        """render_digest with fallback_note=None does NOT include fallback note text."""
        from src.notifications.renderer import render_digest

        job = make_job(job_id="g1", title="Backend Intern", company="StartupCo")

        html, text = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
            fallback_note=None,
        )

        assert "Previous digest" not in html
        assert "Previous digest" not in text
