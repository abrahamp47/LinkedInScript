from __future__ import annotations

"""LinkedInScript — Daily LinkedIn tech intern job monitor.

Usage:
    python main.py              Fetch jobs and print summary
    python main.py --verbose    Print full job details
    python main.py --dry-run    Preview digest without sending email
    python main.py --test-email Verify SMTP configuration
    python main.py --status     Print run status and exit
    python main.py --install    Register daily Task Scheduler job
    python main.py --uninstall-task  Remove scheduled task only
    python main.py --uninstall  Remove all data, logs, scheduled task, and config
    python main.py --help       Show usage information
"""

import argparse
import logging
import os
import shutil
import smtplib
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

# Absolute path resolution for Task Scheduler compatibility
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config, validate_config, setup_logging, load_env
from src.filters.pipeline import run_filter_pipeline
from src.notifications import prepare_email_data, make_subject, render_digest, send_email, send_test_email
from src.scraper.linkedin import scrape_all_keywords
from src.scheduling import (
    record_run_start,
    record_run_complete,
    check_catchup,
    check_health,
    check_reauth_alert,
    print_status,
    SUCCESS,
    ZERO_RESULTS,
    SCRAPE_ERROR,
    PIPELINE_ERROR,
)
from src.storage import (
    store_jobs,
    get_new_jobs,
    mark_as_notified,
    generate_run_id,
    detect_reposts,
    group_by_company,
)
from src.storage.database import purge_old_entries

logger = logging.getLogger(__name__)


def cleanup_old_digests(output_dir: Path, max_age_days: int = 7) -> int:
    """Delete HTML digest files older than max_age_days from output directory.

    Per D-10: Auto-delete HTML files older than 7 days on startup.
    Only deletes FILES matching digest-*.html — never the directory itself (Pitfall 3).

    Args:
        output_dir: Path to the output directory.
        max_age_days: Maximum age in days before deletion (default 7).

    Returns:
        Count of files deleted.
    """
    if not output_dir.exists():
        return 0

    cutoff = time.time() - (max_age_days * 86400)
    deleted = 0
    for f in output_dir.glob("digest-*.html"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
    return deleted


def check_previous_fallback(output_dir: Path) -> tuple[str | None, list[Path]]:
    """Check for existing fallback digest files from previous failed sends.

    Addresses review item 2 (full lifecycle): checks for ANY existing digest-*.html
    files (not just yesterday's — handles multi-day outages).

    Args:
        output_dir: Path to the output directory.

    Returns:
        Tuple of (note_string, list_of_matching_paths).
        Returns (None, []) if no fallback files exist or directory doesn't exist.
    """
    if not output_dir.exists():
        return None, []

    fallback_files = list(output_dir.glob("digest-*.html"))
    if fallback_files:
        note = (
            "Note: Previous digest(s) were saved locally (email failed). "
            "Check output/ directory."
        )
        return note, fallback_files

    return None, []


def _uninstall(project_root: Path) -> None:
    """Remove scheduled task, database, logs, output files, and user config."""
    print("LinkedInScript Uninstall")
    print("=" * 40)

    # 1. Remove Windows Task Scheduler task
    print("\n[1/5] Removing scheduled task...")
    from src.scheduling.task_scheduler import uninstall as uninstall_task
    uninstall_task()

    # 2. Remove database
    print("\n[2/5] Removing database...")
    data_dir = project_root / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
        print("  data/ directory removed.")
    else:
        print("  No database found.")

    # 3. Remove logs
    print("\n[3/5] Removing logs...")
    logs_dir = project_root / "logs"
    if logs_dir.exists():
        shutil.rmtree(logs_dir)
        print("  logs/ directory removed.")
    else:
        print("  No logs found.")

    # 4. Remove output directory (fallback HTML digests)
    print("\n[4/5] Removing output files...")
    output_dir = project_root / "output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
        print("  output/ directory removed.")
    else:
        print("  No output files found.")

    # 5. Remove user config (keep config.example.yaml)
    print("\n[5/5] Removing user configuration...")
    config_file = project_root / "config.yaml"
    env_file = project_root / ".env"
    removed = []
    if config_file.exists():
        config_file.unlink()
        removed.append("config.yaml")
    if env_file.exists():
        env_file.unlink()
        removed.append(".env")
    if removed:
        print(f"  Removed: {', '.join(removed)}")
    else:
        print("  No user config found.")

    print("\n" + "=" * 40)
    print("Uninstall complete. Source code preserved.")
    print("To reinstall: python main.py (recreates config)")


def main():
    """Main entry point for LinkedInScript."""
    parser = argparse.ArgumentParser(
        description="LinkedIn Tech Intern Job Monitor — "
        "searches LinkedIn daily for new tech internship openings."
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full job details instead of summary count",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview digest output without sending email or updating database",
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Verify SMTP configuration by sending a test message, then exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print last run time, failure count, and next scheduled time, then exit",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Register daily Task Scheduler job (runs at config schedule.time)",
    )
    parser.add_argument(
        "--uninstall-task",
        action="store_true",
        help="Remove the scheduled task only (keeps data and config)",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove scheduled task, database, logs, output files, and config",
    )
    args = parser.parse_args()

    # First-run check: copy config.example.yaml if config.yaml doesn't exist (D-06)
    config_path = PROJECT_ROOT / "config.yaml"
    example_path = PROJECT_ROOT / "config.example.yaml"

    if not config_path.exists():
        if example_path.exists():
            shutil.copy(example_path, config_path)
            print(
                "Config file created at config.yaml -- "
                "please review settings and run again."
            )
        else:
            print("ERROR: config.example.yaml not found. Cannot create config.")
            sys.exit(1)
        sys.exit(0)

    # --uninstall: remove all data, scheduled task, and generated files
    if args.uninstall:
        _uninstall(PROJECT_ROOT)
        sys.exit(0)

    # Load environment variables from .env (D-05)
    load_env(PROJECT_ROOT)

    # Load and validate configuration (CONF-01)
    try:
        config = load_config(config_path)
        validate_config(config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    # --install: register daily Task Scheduler job
    if args.install:
        from src.scheduling.task_scheduler import install
        success = install(config)
        sys.exit(0 if success else 1)

    # --uninstall-task: remove scheduled task only
    if args.uninstall_task:
        from src.scheduling.task_scheduler import uninstall
        success = uninstall()
        sys.exit(0 if success else 1)

    # --status: print run info and exit (D-13)
    # Exits with code 0. Runs BEFORE setup_logging — no side effects.
    if args.status:
        print_status(config)
        sys.exit(0)

    # --test-email: verify SMTP config and exit (SETUP-01, D-10)
    # Exits with code 0 on success, 1 on failure (review concern 7).
    # Runs BEFORE setup_logging — no side effects.
    if args.test_email:
        try:
            send_test_email(config)
            sys.exit(0)
        except (ValueError, smtplib.SMTPException):
            sys.exit(1)

    # Setup logging (CONF-03)
    setup_logging(config, PROJECT_ROOT)
    logger.info("LinkedInScript starting")

    # Catch-up detection (D-07): log if last run was >24h ago
    if not args.dry_run:
        check_catchup()

    # Extract config sections for scraper
    search_config = config["search"]
    scraping_config = config.get("scraping", {})

    logger.info(
        "Config loaded: %d keywords x %d locations",
        len(search_config["keywords"]),
        len(search_config["locations"]),
    )

    # Ensure data/ directory exists for SQLite database (D-07)
    os.makedirs(PROJECT_ROOT / "data", exist_ok=True)

    # DB retention purge (D-12): run at pipeline start, after init, before scraping
    # Skip during --dry-run (consistent with skip of other DB mutations)
    if not args.dry_run:
        retention_days = config.get("database", {}).get("retention_days", 90)
        purge_old_entries(retention_days)

    # Output directory cleanup (D-10): delete old fallback HTML files (>7 days)
    output_dir = PROJECT_ROOT / "output"
    deleted_digests = cleanup_old_digests(output_dir)
    if deleted_digests > 0:
        logger.info("Cleaned up %d old digest file(s) from output/", deleted_digests)

    # Check for previous fallback files (D-09, review item 2)
    fallback_note, fallback_files = check_previous_fallback(output_dir)

    # Step A: Generate unique run identifier
    run_id = generate_run_id()

    # Record run start (skipped for --dry-run)
    if not args.dry_run:
        record_run_start(run_id)

    # CRITICAL: pipeline_status starts as PIPELINE_ERROR. The try block's normal
    # completion overwrites it with the correct status. If an exception occurs,
    # finally sees PIPELINE_ERROR — no zombie "running" rows. (Review concern: zombie runs)
    pipeline_status = PIPELINE_ERROR
    jobs = []
    new_jobs = []

    total_block = False

    try:
        # Run scraper across all keyword x location combinations (D-01, D-02, D-03)
        scrape_result = scrape_all_keywords(
            keywords=search_config["keywords"],
            locations=search_config["locations"],
            results_per_keyword=search_config.get("results_wanted", 75),
            hours_old=search_config.get("hours_old", 24),
            min_delay=scraping_config.get("min_delay", 5),
            max_delay=scraping_config.get("max_delay", 12),
        )

        # Unpack ScrapeResult (Phase 6: resilience)
        jobs = scrape_result.jobs
        scrape_warnings = scrape_result.warnings

        # Total-block check (D-03): all combos blocked — skip email entirely
        if (
            scrape_result.blocked_combos == scrape_result.total_combos
            and scrape_result.total_combos > 0
        ):
            total_block = True
            pipeline_status = SCRAPE_ERROR
            logger.error(
                "All %d search combos were blocked — skipping email digest send",
                scrape_result.total_combos,
            )

        if not total_block:
            # Construct scrape_warning_summary for email footer (D-05)
            scrape_warning_summary = None
            if scrape_result.blocked_combos > 0:
                scrape_warning_summary = (
                    f"Note: {scrape_result.blocked_combos} of "
                    f"{scrape_result.total_combos} search combinations "
                    f"were blocked by LinkedIn."
                )

        # When total block, store whatever we have (empty list) and skip the rest
        if not total_block:
            # Run filter pipeline (Phase 2: Location -> Company -> Watchlist)
            filter_result = run_filter_pipeline(jobs, config)

            # Pipeline order (authoritative — per cross-AI review consensus):
            # store_jobs() -> get_new_jobs() -> detect_reposts() -> group_by_company() -> output -> mark_as_notified()

            # Step B: Store ALL scraped jobs with filter_passed=False (D-08: store pre-filter for analytics)
            store_jobs(jobs, filter_passed=False, run_id=run_id)

            # Step C: Store filtered jobs with filter_passed=True (upgrades flag via MAX)
            store_jobs(filter_result.passed, filter_passed=True, run_id=run_id)

            # Step D: Determine which filtered jobs are genuinely new (not previously notified)
            new_ids = get_new_jobs([j.job_id for j in filter_result.passed])
            new_ids_set = set(new_ids)

            # Step E: Build list of new Job instances
            new_jobs = [j for j in filter_result.passed if j.job_id in new_ids_set]

            # Step F: Detect reposts among new jobs (DEDUP-02)
            repost_results = detect_reposts(new_jobs, run_id)
            repost_ids = {r["job"].job_id for r in repost_results if r["is_repost"]}
            n_reposts = len(repost_ids)

            # Step G: Group new jobs by company for presentation (DEDUP-03, D-05/D-06)
            grouped = group_by_company(new_jobs)

            # Step H: Output — grouped display with [REPOST] labels
            duplicates_skipped = len(filter_result.passed) - len(new_jobs)

            print(
                f"Found {len(new_jobs)} new jobs "
                f"({n_reposts} reposts, "
                f"{duplicates_skipped} duplicates skipped, "
                f"from {filter_result.stats['total_in']} scraped)."
            )

            if args.verbose and new_jobs:
                print()
                for company, company_jobs in grouped.items():
                    listing_word = "listing" if len(company_jobs) == 1 else "listings"
                    print(f"  {company} ({len(company_jobs)} {listing_word}):")
                    for job in company_jobs:
                        # Build prefix: [REPOST] and [WATCHLIST] can co-exist (D-02)
                        prefix = ""
                        if job.job_id in repost_ids:
                            prefix += "[REPOST] "
                        if job.watchlist_match:
                            prefix += "[WATCHLIST] "
                        print(f"    {prefix}{job.title}")
                        print(f"      Location: {job.location}")
                        print(f"      URL: {job.job_url}")
                    print()

            # Step I: Email delivery (Phase 4) — send digest if email is enabled.
            # CRITICAL (review concern 1): mark_as_notified runs ONLY after successful send.
            # If SMTP fails, jobs remain unnotified and re-appear on next run.
            email_enabled = config.get("email", {}).get("enabled", False)

            # --dry-run behavior (D-07, D-08, NOTF-04, addresses review concern 2):
            # NOTE: --dry-run does not mark jobs as notified. Running --dry-run multiple
            # times before a real run means all accumulated new jobs will appear in the
            # next real email. This is intentional — dry-run is purely observational.
            if args.dry_run:
                # Prepare email data and render regardless of email_enabled setting
                watchlist_jobs, general_jobs, repost_jobs = prepare_email_data(new_jobs, repost_ids)
                subject = make_subject(len(new_jobs))
                date_str = date.today().strftime("%B %d, %Y")

                # Render digest (D-08: print plain-text to console)
                # CRITICAL (review concern 2): even when new_jobs is empty (0 results),
                # render_digest still produces a heartbeat plain-text message.
                html_body, text_body = render_digest(
                    watchlist_jobs, general_jobs, repost_jobs, subject, date_str,
                    scrape_warning_summary=scrape_warning_summary,
                    fallback_note=fallback_note,
                )

                # Print the plain-text digest to stdout (what would be emailed)
                print(text_body.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"))

                # Do NOT call send_email — dry-run is read-only for email
                # Do NOT call mark_as_notified — dry-run is read-only for database
                print(
                    "Dry run complete. No email sent, no jobs marked as notified.",
                    file=sys.stderr,
                )
            elif email_enabled:
                # Prepare email data: split into sections per D-05
                watchlist_jobs, general_jobs, repost_jobs = prepare_email_data(new_jobs, repost_ids)
                subject = make_subject(len(new_jobs))
                date_str = date.today().strftime("%B %d, %Y")

                # Render HTML + plain-text (D-06/D-13: send even for 0 new jobs as heartbeat)
                html_body, text_body = render_digest(
                    watchlist_jobs, general_jobs, repost_jobs, subject, date_str,
                    scrape_warning_summary=scrape_warning_summary,
                    fallback_note=fallback_note,
                )

                try:
                    send_email(config, subject, html_body, text_body)
                    logger.info("Email digest sent: %s", subject)
                    # Email succeeded — safe to mark as notified
                    mark_as_notified(new_ids)
                    # Delete previous fallback files after successful send (review item 2c)
                    if fallback_files:
                        for f in fallback_files:
                            f.unlink(missing_ok=True)
                        logger.info(
                            "Deleted %d previous fallback file(s) after successful send",
                            len(fallback_files),
                        )
                except (smtplib.SMTPException, ValueError) as e:
                    logger.error(
                        "SMTP send failed: %s — saving digest to file", e
                    )
                    # Save HTML fallback (D-06, review item 6: explicit mkdir)
                    output_dir.mkdir(parents=True, exist_ok=True)
                    fallback_path = output_dir / f"digest-{date.today().isoformat()}.html"
                    fallback_path.write_text(html_body, encoding="utf-8")
                    print(
                        f"Email failed -- digest saved to {fallback_path}",
                        file=sys.stderr,
                    )
            else:
                # Email disabled — mark_as_notified runs unconditionally (existing behavior)
                mark_as_notified(new_ids)

            # Determine pipeline status based on results
            if len(jobs) == 0:
                pipeline_status = SCRAPE_ERROR
            elif len(new_jobs) == 0:
                pipeline_status = ZERO_RESULTS
            else:
                pipeline_status = SUCCESS

            logger.info(
                "LinkedInScript complete — %d new jobs (%d reposts), %d filtered, %d raw, %d duplicates skipped",
                len(new_jobs),
                n_reposts,
                len(filter_result.passed),
                filter_result.stats["total_in"],
                duplicates_skipped,
            )
    finally:
        # CRITICAL: record_run_complete ALWAYS fires (even on uncaught exception).
        # pipeline_status starts as PIPELINE_ERROR and is only overwritten on normal completion.
        # This prevents zombie "running" rows in the runs table.
        if not args.dry_run:
            record_run_complete(
                run_id,
                status=pipeline_status,
                jobs_found=len(jobs),
                jobs_notified=len(new_jobs),
            )
            check_health(config)
            # Alert (once) if LinkedIn login is required for unattended runs
            check_reauth_alert(config)


if __name__ == "__main__":
    main()
