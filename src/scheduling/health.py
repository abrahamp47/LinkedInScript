"""Health monitoring -- alert emails and status CLI.

Implements:
- check_health: Send alert after 2+ consecutive scrape_error days (D-10, D-11, D-12)
- print_status: Print last run time, failures, next scheduled time (D-13)

Health alert logic:
- Only triggers on 'scrape_error' (technical failure), NOT 'zero_results' (normal day)
- Sent at most once per failure streak (health_alert_sent flag)
- Flag resets when any non-scrape_error run completes (success OR zero_results)
"""

import logging
import subprocess

from src.notifications.sender import send_email
from src.scheduling.runs import get_consecutive_failures, get_last_run_time
from src.storage.database import get_connection, init_db

logger = logging.getLogger(__name__)

# Health alert email template (simple HTML, not Jinja2)
HEALTH_ALERT_HTML = """\
<html><body>
<h2 style="color: #d32f2f;">LinkedInScript Health Alert</h2>
<p><strong>{count} consecutive days with zero results.</strong></p>
<p>The scraper has not found any jobs across all keyword/location combinations
for the last {count} run(s).</p>
<h3>Suggested Actions:</h3>
<ul>
<li>Check if LinkedIn is accessible from this machine</li>
<li>Review logs at <code>logs/run.log</code> for errors</li>
<li>Verify search keywords still produce results manually</li>
<li>Check if python-jobspy needs updating</li>
</ul>
</body></html>
"""

HEALTH_ALERT_TEXT = """\
LinkedInScript Health Alert

{count} consecutive days with zero results.

The scraper has not found any jobs across all keyword/location combinations
for the last {count} run(s).

Suggested Actions:
- Check if LinkedIn is accessible from this machine
- Review logs at logs/run.log for errors
- Verify search keywords still produce results manually
- Check if python-jobspy needs updating
"""


def check_health(config: dict) -> None:
    """Check health status and send alert if threshold reached.

    Logic (D-10, D-11, D-12):
    1. If latest completed run has status != 'scrape_error': reset health_alert_sent flag
    2. If consecutive scrape_error count >= 2 AND health_alert_sent == 0: send alert, set flag
    3. Otherwise: do nothing

    Args:
        config: Full config dict (passed to send_email for SMTP settings).
    """
    failures = get_consecutive_failures()

    with get_connection() as conn:
        init_db(conn)

        # Check if latest completed run is NOT a scrape_error -- reset flag
        latest = conn.execute(
            """SELECT run_id, status, health_alert_sent FROM runs
               WHERE status IN ('success', 'zero_results', 'scrape_error')
               ORDER BY completed_at DESC LIMIT 1"""
        ).fetchone()

        if latest is None:
            return

        if latest["status"] != "scrape_error":
            # Reset the health_alert_sent flag (streak broken)
            conn.execute(
                "UPDATE runs SET health_alert_sent = 0 WHERE health_alert_sent = 1"
            )
            return

        # Check if alert already sent for this streak
        # Any run in the current scrape_error streak with health_alert_sent=1
        # means we already alerted for this streak
        alert_already_sent = conn.execute(
            """SELECT COUNT(*) as cnt FROM runs
               WHERE status = 'scrape_error' AND health_alert_sent = 1"""
        ).fetchone()

        if alert_already_sent and alert_already_sent["cnt"] > 0:
            return

    # Threshold check: only alert on 2+ consecutive failures
    if failures < 2:
        return

    # Send health alert email
    subject = (
        f"LinkedInScript: Health Alert -- "
        f"{failures} consecutive days with zero results"
    )
    html_body = HEALTH_ALERT_HTML.format(count=failures)
    text_body = HEALTH_ALERT_TEXT.format(count=failures)

    try:
        send_email(config, subject, html_body, text_body)
        logger.warning("Health alert sent: %d consecutive scrape failures", failures)
    except Exception as e:
        logger.error("Failed to send health alert: %s", e)
        return

    # Mark alert as sent on the latest scrape_error run
    with get_connection() as conn:
        init_db(conn)
        conn.execute(
            """UPDATE runs SET health_alert_sent = 1
               WHERE status = 'scrape_error'
               AND completed_at = (
                   SELECT MAX(completed_at) FROM runs WHERE status = 'scrape_error'
               )"""
        )


def print_status(config: dict) -> None:
    """Print run status information (D-13).

    Always prints DB-derived info (last run time, failure count).
    Attempts Task Scheduler query for next scheduled time -- graceful degradation
    if PowerShell unavailable or task not registered (T-05-02).

    Format matches --test-email numbered style: [1/3], [2/3], [3/3].

    Args:
        config: Full config dict (unused currently but kept for future extension).
    """
    # [1/3] Last run time (always available from DB)
    last_run = get_last_run_time()
    print(f"[1/3] Last run: {last_run or 'Never'}")

    # [2/3] Consecutive failures (always available from DB)
    failures = get_consecutive_failures()
    print(f"[2/3] Consecutive failures: {failures}")

    # [3/3] Next scheduled time (requires Task Scheduler query)
    next_run = _get_next_scheduled_time()
    print(f"[3/3] Next scheduled run: {next_run}")


def _get_next_scheduled_time() -> str:
    """Query Task Scheduler for next run time via PowerShell.

    Returns:
        Next run time string, or "Not scheduled" / "Not available (...)" on failure.
    """
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "try { (Get-ScheduledTaskInfo -TaskName 'LinkedInScript').NextRunTime } "
                "catch { 'Not scheduled' }",
            ],
            capture_output=True,
            text=True,
            timeout=10,  # T-05-02: prevent hang
        )
        output = result.stdout.strip()
        if not output or "Not scheduled" in output:
            return "Not scheduled"
        return output
    except subprocess.TimeoutExpired:
        return "Not available (Task Scheduler query timed out)"
    except (FileNotFoundError, OSError):
        return "Not available (Task Scheduler query failed)"
