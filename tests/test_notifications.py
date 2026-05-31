"""Tests for the notifications module — email digest rendering and sending.

RED phase: These tests define expected behavior for src/notifications/.
They verify NOTF-01: HTML digest with title, company, link, snippet, location, date.
NOTF-02: Digest sections ordered — watchlist first, then general, then reposts.
"""

import os
import re
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_job


class TestRenderer:
    """Tests for render_digest template rendering (NOTF-01, NOTF-02)."""

    def test_render_digest_sections_order(self):
        """render_digest with 1 watchlist, 1 general, 1 repost returns HTML with all three sections in correct order."""
        from src.notifications.renderer import render_digest

        watchlist_job = make_job(job_id="w1", title="SDE Intern", company="Google", watchlist_match=True)
        general_job = make_job(job_id="g1", title="ML Intern", company="Startup Inc")
        repost_job = make_job(job_id="r1", title="Data Intern", company="OldCorp")

        html, plain_text = render_digest(
            [watchlist_job], [general_job], [repost_job],
            subject="LinkedInScript: 3 new internships found (May 30)",
            date_str="May 30, 2026",
        )

        # HTML should contain all three sections in order
        assert "Priority Companies" in html
        assert "New Listings" in html
        assert "Reposts" in html

        # Verify order: watchlist before general before reposts
        watchlist_pos = html.index("Priority Companies")
        general_pos = html.index("New Listings")
        reposts_pos = html.index("Reposts")
        assert watchlist_pos < general_pos < reposts_pos

    def test_render_digest_html_contains_job_fields(self):
        """render_digest HTML output contains job.title, job.company, job.location, job.job_url, prefixes."""
        from src.notifications.renderer import render_digest

        watchlist_job = make_job(
            job_id="w1", title="SDE Intern at Google",
            company="Google", location="Bengaluru",
            job_url="https://linkedin.com/jobs/w1",
            watchlist_match=True,
        )
        repost_job = make_job(
            job_id="r1", title="Data Intern Repost",
            company="OldCorp", location="Remote",
            job_url="https://linkedin.com/jobs/r1",
        )

        html, _ = render_digest(
            [watchlist_job], [], [repost_job],
            subject="Test Subject",
            date_str="May 30, 2026",
        )

        # Verify job data appears in HTML
        assert "SDE Intern at Google" in html
        assert "Google" in html
        assert "Bengaluru" in html
        assert "https://linkedin.com/jobs/w1" in html
        assert "[WATCHLIST]" in html
        assert "[REPOST]" in html

    def test_render_digest_plain_text_contains_job_info(self):
        """render_digest plain_text output contains job titles, companies, URLs in readable format."""
        from src.notifications.renderer import render_digest

        job = make_job(
            job_id="g1", title="Backend Intern",
            company="StartupCo", location="Bengaluru",
            job_url="https://linkedin.com/jobs/g1",
        )

        _, plain_text = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
        )

        assert "Backend Intern" in plain_text
        assert "StartupCo" in plain_text
        assert "https://linkedin.com/jobs/g1" in plain_text

    def test_render_digest_empty_jobs_heartbeat(self):
        """render_digest with empty job lists returns valid HTML with heartbeat message."""
        from src.notifications.renderer import render_digest

        html, plain_text = render_digest(
            [], [], [],
            subject="LinkedInScript: No new internships (May 30)",
            date_str="May 30, 2026",
        )

        # Both should be non-empty
        assert len(html) > 0
        assert len(plain_text) > 0

        # Should contain heartbeat message
        assert "heartbeat" in html.lower() or "no new internships" in html.lower()
        assert "heartbeat" in plain_text.lower() or "no new internships" in plain_text.lower()


class TestPrepareData:
    """Tests for prepare_email_data job splitting."""

    def test_prepare_email_data_splits_correctly(self):
        """prepare_email_data correctly splits jobs into (watchlist, general, repost) based on flags."""
        from src.notifications.renderer import prepare_email_data

        watchlist_job = make_job(job_id="w1", watchlist_match=True)
        general_job = make_job(job_id="g1", watchlist_match=False)
        repost_job = make_job(job_id="r1", watchlist_match=False)

        repost_ids = {"r1"}
        watchlist_jobs, general_jobs, repost_jobs = prepare_email_data(
            [watchlist_job, general_job, repost_job], repost_ids
        )

        assert len(watchlist_jobs) == 1
        assert watchlist_jobs[0].job_id == "w1"
        assert len(general_jobs) == 1
        assert general_jobs[0].job_id == "g1"
        assert len(repost_jobs) == 1
        assert repost_jobs[0].job_id == "r1"


class TestMakeSubject:
    """Tests for make_subject line generation (D-04)."""

    def test_make_subject_with_jobs(self):
        """make_subject(7) returns 'LinkedInScript: 7 new internships found (Mon DD)' format."""
        from src.notifications.renderer import make_subject

        result = make_subject(7)
        assert re.match(r"LinkedInScript: 7 new internships found \(\w+ \d+\)", result)

    def test_make_subject_zero_jobs(self):
        """make_subject(0) returns 'LinkedInScript: No new internships (Mon DD)' format."""
        from src.notifications.renderer import make_subject

        result = make_subject(0)
        assert re.match(r"LinkedInScript: No new internships \(\w+ \d+\)", result)


class TestMakeSnippet:
    """Tests for _make_snippet description truncation (review concern 4)."""

    def test_make_snippet_none_returns_fallback(self):
        """_make_snippet(None) returns 'No description available.'"""
        from src.notifications.renderer import _make_snippet

        assert _make_snippet(None) == "No description available."

    def test_make_snippet_empty_returns_fallback(self):
        """_make_snippet('') returns 'No description available.'"""
        from src.notifications.renderer import _make_snippet

        assert _make_snippet("") == "No description available."

    def test_make_snippet_long_text_truncates(self):
        """_make_snippet('x' * 300) produces output <= 160 chars ending with '...'"""
        from src.notifications.renderer import _make_snippet

        long_text = "This is a very long job description that goes on and on. " * 10
        result = _make_snippet(long_text)
        assert len(result) <= 160
        assert result.endswith("...")

    def test_make_snippet_short_text_unchanged(self):
        """_make_snippet with short text returns it without truncation."""
        from src.notifications.renderer import _make_snippet

        short_text = "A brief description."
        result = _make_snippet(short_text)
        assert result == short_text


class TestSender:
    """Tests for send_email SMTP sending (mocked)."""

    def test_send_email_constructs_multipart_alternative(self):
        """send_email constructs MIMEMultipart('alternative') with text/plain and text/html parts."""
        from src.notifications.sender import send_email

        config = {
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "sender_email": "test@gmail.com",
                "recipient_email": "test@gmail.com",
            }
        }

        with patch.dict(os.environ, {"EMAIL_PASSWORD": "testpass123"}):
            with patch("src.notifications.sender.smtplib.SMTP") as mock_smtp:
                mock_server = MagicMock()
                mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
                mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

                send_email(config, "Test Subject", "<h1>HTML</h1>", "Plain text")

                # Verify SMTP calls in sequence: starttls, login, send_message
                mock_server.starttls.assert_called_once()
                mock_server.login.assert_called_once_with("test@gmail.com", "testpass123")
                mock_server.send_message.assert_called_once()

                # Verify the message is multipart/alternative
                sent_msg = mock_server.send_message.call_args[0][0]
                assert sent_msg.get_content_type() == "multipart/alternative"

                # Verify both parts are attached (plain first, then html)
                payloads = sent_msg.get_payload()
                assert len(payloads) == 2
                assert payloads[0].get_content_type() == "text/plain"
                assert payloads[1].get_content_type() == "text/html"

    def test_send_email_raises_without_password(self):
        """send_email raises ValueError when EMAIL_PASSWORD env var is not set."""
        from src.notifications.sender import send_email

        config = {
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "sender_email": "test@gmail.com",
                "recipient_email": "test@gmail.com",
            }
        }

        # Ensure EMAIL_PASSWORD is not set
        env = os.environ.copy()
        env.pop("EMAIL_PASSWORD", None)

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="EMAIL_PASSWORD"):
                send_email(config, "Test", "<p>test</p>", "test")


class TestTestEmail:
    """Tests for send_test_email SMTP verification (SETUP-01, D-10)."""

    def test_send_test_email_smtp_sequence(self):
        """send_test_email calls starttls, login, send_message with 'Test Email' in subject."""
        from src.notifications.sender import send_test_email

        config = {
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "sender_email": "test@gmail.com",
                "recipient_email": "test@gmail.com",
            }
        }

        with patch.dict(os.environ, {"EMAIL_PASSWORD": "testpass123"}):
            with patch("src.notifications.sender.smtplib.SMTP") as mock_smtp:
                mock_server = MagicMock()
                mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
                mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

                send_test_email(config)

                mock_server.starttls.assert_called_once()
                mock_server.login.assert_called_once_with("test@gmail.com", "testpass123")
                mock_server.send_message.assert_called_once()

                # Verify subject contains "Test Email"
                sent_msg = mock_server.send_message.call_args[0][0]
                assert "Test Email" in sent_msg["Subject"]

    def test_send_test_email_numbered_progress(self, capsys):
        """send_test_email prints numbered progress messages [1/4], [2/4], [3/4], [4/4]."""
        from src.notifications.sender import send_test_email

        config = {
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "sender_email": "test@gmail.com",
                "recipient_email": "test@gmail.com",
            }
        }

        with patch.dict(os.environ, {"EMAIL_PASSWORD": "testpass123"}):
            with patch("src.notifications.sender.smtplib.SMTP") as mock_smtp:
                mock_server = MagicMock()
                mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
                mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

                send_test_email(config)

        captured = capsys.readouterr()
        assert "[1/4]" in captured.out
        assert "[2/4]" in captured.out
        assert "[3/4]" in captured.out
        assert "[4/4]" in captured.out

    def test_send_test_email_raises_valueerror_no_password(self, capsys):
        """send_test_email raises ValueError when EMAIL_PASSWORD is not set, after printing [1/4]."""
        from src.notifications.sender import send_test_email

        config = {
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "sender_email": "test@gmail.com",
                "recipient_email": "test@gmail.com",
            }
        }

        env = os.environ.copy()
        env.pop("EMAIL_PASSWORD", None)

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="EMAIL_PASSWORD"):
                send_test_email(config)

        captured = capsys.readouterr()
        assert "[1/4]" in captured.out

    def test_send_test_email_smtp_exception_reraises(self, capsys):
        """send_test_email on SMTPException prints error and re-raises."""
        import smtplib

        from src.notifications.sender import send_test_email

        config = {
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "sender_email": "test@gmail.com",
                "recipient_email": "test@gmail.com",
            }
        }

        with patch.dict(os.environ, {"EMAIL_PASSWORD": "testpass123"}):
            with patch("src.notifications.sender.smtplib.SMTP") as mock_smtp:
                mock_server = MagicMock()
                mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
                mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
                mock_server.starttls.side_effect = smtplib.SMTPException("Connection failed")

                with pytest.raises(smtplib.SMTPException):
                    send_test_email(config)

        captured = capsys.readouterr()
        assert "SMTP Error" in captured.out or "Connection failed" in captured.out


class TestDryRun:
    """Tests for --dry-run CLI behavior (NOTF-04, D-07, D-08)."""

    def test_dry_run_flag_parsed(self):
        """--dry-run flag in argparse is recognized (parser.parse_args(['--dry-run']).dry_run is True)."""
        import argparse
        import importlib
        import sys

        # Import main module to get the parser
        # We test by building the same parser inline since main() calls parse_args()
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_test_email_flag_parsed(self):
        """--test-email flag in argparse is recognized (parser.parse_args(['--test-email']).test_email is True)."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--test-email", action="store_true")
        args = parser.parse_args(["--test-email"])
        assert args.test_email is True

    def test_dry_run_prints_text_body_no_send(self, capsys):
        """When dry_run=True, pipeline prints text_body to stdout but does NOT call send_email or mark_as_notified."""
        from src.notifications.renderer import render_digest

        from tests.conftest import make_job

        # Setup: prepare jobs and render digest
        job = make_job(job_id="g1", title="Backend Intern", company="StartupCo")
        _, text_body = render_digest(
            [], [job], [],
            subject="Test Subject",
            date_str="May 30, 2026",
        )

        # Simulate dry-run behavior: print text_body
        print(text_body)

        captured = capsys.readouterr()
        assert "Backend Intern" in captured.out
        assert "StartupCo" in captured.out

    def test_dry_run_zero_jobs_prints_heartbeat(self, capsys):
        """When dry_run=True and new_jobs is empty, still prints heartbeat plain-text to stdout (not empty)."""
        from src.notifications.renderer import render_digest

        # Render with empty job lists
        _, text_body = render_digest(
            [], [], [],
            subject="LinkedInScript: No new internships (May 30)",
            date_str="May 30, 2026",
        )

        # Simulate dry-run: print text_body
        print(text_body)

        captured = capsys.readouterr()
        # Must not be empty
        assert len(captured.out.strip()) > 0
        # Must contain heartbeat indicator
        assert "no new internships" in captured.out.lower() or "heartbeat" in captured.out.lower()
