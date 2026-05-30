"""Notification sender — SMTP connection, message construction, and delivery.

Connects to Gmail SMTP with STARTTLS on port 587, builds MIMEMultipart('alternative')
message with both text/plain and text/html parts, and sends via authenticated session.

On failure: raises smtplib.SMTPException — caller in main.py handles the error.
This is intentional (review concern 1): if send_email raises, mark_as_notified must NOT run.

Exports:
    send_email(config, subject, html_body, text_body) -> None
    send_test_email(config) -> None
"""

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

logger = logging.getLogger(__name__)


def send_email(config: dict, subject: str, html_body: str, text_body: str) -> None:
    """Send an HTML email with plain-text fallback via SMTP.

    Builds MIMEMultipart('alternative') with both text/plain and text/html parts
    (review concern 3). Uses STARTTLS with ssl.create_default_context() for secure
    transport (T-04-03). Timeout of 30s prevents infinite hang (T-04-04).

    Args:
        config: Full config dict (expects config['email'] section with
                smtp_host, smtp_port, sender_email, recipient_email).
        subject: Email subject line.
        html_body: Rendered HTML content.
        text_body: Plain-text fallback content.

    Raises:
        smtplib.SMTPException: On any SMTP failure (connection, auth, send).
        ValueError: If EMAIL_PASSWORD env var is not set (T-04-01).
    """
    email_cfg = config["email"]

    # T-04-01: Password from environment only, never logged
    password = os.environ.get("EMAIL_PASSWORD")
    if not password:
        raise ValueError(
            "EMAIL_PASSWORD not set in environment. "
            "Add it to .env file (see .env.example for setup instructions)."
        )

    # Build MIMEMultipart('alternative') — plain-text first, then HTML (order matters)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_cfg["sender_email"]
    msg["To"] = email_cfg["recipient_email"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(
        domain=email_cfg["sender_email"].split("@")[1]
    )

    # Attach plain-text FIRST, then HTML (per MIME 'alternative' convention)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # T-04-03: STARTTLS with verified certificate
    context = ssl.create_default_context()

    # T-04-04: Explicit timeout prevents infinite hang in Task Scheduler
    with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"], timeout=30) as server:
        server.starttls(context=context)
        server.login(email_cfg["sender_email"], password)
        server.send_message(msg)

    logger.info("Email sent successfully: %s", subject)


def send_test_email(config: dict) -> None:
    """Verify SMTP connection and send a test message (D-10, SETUP-01).

    Prints numbered step-by-step progress (review concern 5):
    [1/4] Checking config, [2/4] Connecting, [3/4] Authenticating, [4/4] Sending.

    Args:
        config: Full config dict with 'email' section.

    Raises:
        ValueError: If EMAIL_PASSWORD is not set in environment.
        smtplib.SMTPException: On any SMTP failure (connection, auth, send).
    """
    email_cfg = config["email"]

    # [1/4] Check configuration
    print("[1/4] Checking email configuration...")
    password = os.environ.get("EMAIL_PASSWORD")
    if not password:
        raise ValueError(
            "EMAIL_PASSWORD not set in .env file. See docs/SETUP.md."
        )
    print("[1/4] Configuration OK.")

    # [2/4] Connect with STARTTLS
    smtp_host = email_cfg["smtp_host"]
    smtp_port = email_cfg["smtp_port"]
    print(f"[2/4] Connecting to {smtp_host}:{smtp_port}...")

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls(context=context)
            print("[2/4] Connected with STARTTLS.")

            # [3/4] Authenticate
            sender_email = email_cfg["sender_email"]
            print("[3/4] Authenticating...")
            server.login(sender_email, password)
            print("[3/4] Authentication successful.")

            # [4/4] Send test message
            recipient_email = email_cfg["recipient_email"]
            print(f"[4/4] Sending test message to {recipient_email}...")

            msg = MIMEMultipart("alternative")
            msg["Subject"] = "LinkedInScript: Test Email - SMTP Working"
            msg["From"] = sender_email
            msg["To"] = recipient_email
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid()

            text_body = (
                "LinkedInScript SMTP Test - "
                "Your email configuration is working correctly."
            )
            html_body = (
                "<h2>LinkedInScript SMTP Test</h2>"
                "<p>Your email configuration is working correctly.</p>"
            )

            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            server.send_message(msg)
            print("[4/4] Test email sent successfully! Check your inbox.")
    except smtplib.SMTPException as e:
        print(f"SMTP Error: {e}")
        raise
