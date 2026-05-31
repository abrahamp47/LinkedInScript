from __future__ import annotations

"""LinkedIn authentication — manages li_at cookie lifecycle with Playwright.

Stores browser state (cookies) in data/linkedin_state.json. On first run or
when the cookie expires, launches a visible browser for manual login. After
that, refreshes the cookie headlessly by loading LinkedIn with saved state.

Exports:
    get_valid_li_at() -> str  (returns a valid li_at cookie, refreshing if needed)
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "linkedin_state.json"
# Marker file written when an unattended run finds the LinkedIn session dead and
# cannot re-authenticate (no TTY for interactive login). health.py reads this to
# send a re-auth alert email. Cleared automatically when a fresh cookie is obtained.
REAUTH_MARKER = PROJECT_ROOT / "data" / ".reauth_needed"
COOKIE_MAX_AGE_DAYS = 30


def _is_interactive() -> bool:
    """True when a terminal is attached (user present to complete a login).

    Task Scheduler runs have no attached TTY, so this returns False there —
    we must not block on a visible browser that nobody can interact with.
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _set_reauth_needed() -> None:
    """Persist the re-auth-needed marker for health.py to pick up."""
    REAUTH_MARKER.parent.mkdir(parents=True, exist_ok=True)
    REAUTH_MARKER.write_text(str(time.time()), encoding="utf-8")


def _clear_reauth_needed() -> None:
    """Remove the re-auth marker (and its alerted sibling) after a successful login."""
    REAUTH_MARKER.unlink(missing_ok=True)
    (REAUTH_MARKER.parent / ".reauth_alerted").unlink(missing_ok=True)


def reauth_needed() -> bool:
    """True if the LinkedIn session is dead and interactive re-login is required."""
    return REAUTH_MARKER.exists()


def _read_stored_cookie() -> tuple[str, float]:
    """Read li_at cookie and timestamp from state file."""
    if not STATE_FILE.exists():
        return "", 0

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("li_at", ""), data.get("updated_at", 0)
    except (json.JSONDecodeError, KeyError):
        return "", 0


def _save_cookie(li_at: str) -> None:
    """Persist li_at cookie with timestamp."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"li_at": li_at, "updated_at": time.time()}),
        encoding="utf-8",
    )


def _is_expired(updated_at: float) -> bool:
    """Check if cookie is older than COOKIE_MAX_AGE_DAYS."""
    if updated_at == 0:
        return True
    age_days = (time.time() - updated_at) / 86400
    return age_days > COOKIE_MAX_AGE_DAYS


def _extract_li_at_from_playwright() -> str:
    """Launch Playwright, load LinkedIn with saved state, extract fresh li_at.

    First run: opens visible browser for manual login.
    Subsequent runs: headless refresh using saved browser context.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed — cannot refresh LinkedIn cookie")
        return ""

    browser_state_path = PROJECT_ROOT / "data" / "linkedin_browser_state.json"
    browser_state_path.parent.mkdir(parents=True, exist_ok=True)

    interactive = _is_interactive()

    with sync_playwright() as p:
        has_saved_state = browser_state_path.exists()

        if has_saved_state:
            # Headless refresh with saved state
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(browser_state_path))
        elif interactive:
            # First time, terminal attached: visible browser for manual login
            print("\n" + "=" * 50)
            print("LinkedIn Login Required (first time only)")
            print("=" * 50)
            print("A browser window will open. Log in to LinkedIn.")
            print("After login completes, the window will close automatically.")
            print("=" * 50 + "\n")
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
        else:
            # No saved state AND no terminal (unattended) — cannot log in.
            logger.error(
                "LinkedIn login required but no saved session and no interactive "
                "terminal. Run 'python main.py' once manually to log in."
            )
            _set_reauth_needed()
            return ""

        page = context.new_page()

        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)

            # Check if we're on the login page (not authenticated)
            if "/login" in page.url or "/checkpoint" in page.url:
                if not interactive:
                    # Unattended run with a dead session — do NOT block on a browser
                    # nobody can see. Flag for re-auth and let health.py alert the user.
                    logger.error(
                        "LinkedIn session expired and this is an unattended run. "
                        "Re-authentication required — run 'python main.py' manually."
                    )
                    _set_reauth_needed()
                    return ""

                if has_saved_state:
                    # Saved state expired — need interactive login
                    browser.close()
                    # Retry with visible browser
                    browser = p.chromium.launch(headless=False)
                    context = browser.new_context()
                    page = context.new_page()
                    print("\nLinkedIn session expired — please log in again.")
                    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)

                # Wait for user to complete login (max 120 seconds)
                page.wait_for_url("**/feed/**", timeout=120000)

            # Give LinkedIn a moment to set all cookies
            page.wait_for_timeout(3000)

            # Extract li_at cookie
            cookies = context.cookies("https://www.linkedin.com")
            li_at = ""
            for cookie in cookies:
                if cookie["name"] == "li_at":
                    li_at = cookie["value"]
                    break

            if li_at:
                # Save browser state for future headless refreshes
                context.storage_state(path=str(browser_state_path))
                _clear_reauth_needed()
                logger.info("LinkedIn cookie refreshed successfully")
            else:
                logger.warning("Could not extract li_at cookie from LinkedIn")

            return li_at

        except Exception as e:
            logger.error("LinkedIn cookie refresh failed: %s", e)
            # A timeout waiting for interactive login also means re-auth is needed
            _set_reauth_needed()
            return ""
        finally:
            browser.close()


def get_valid_li_at() -> str:
    """Get a valid li_at cookie, refreshing if needed.

    Priority:
    1. LINKEDIN_LI_AT from .env (manual override, always wins)
    2. Stored cookie from data/linkedin_state.json (if not expired)
    3. Fresh cookie via Playwright browser refresh

    Returns empty string if all methods fail (falls back to guest API).
    """
    # Priority 1: explicit env var override
    env_cookie = os.environ.get("LINKEDIN_LI_AT", "")
    if env_cookie:
        _clear_reauth_needed()
        return env_cookie

    # Priority 2: stored cookie (if fresh enough)
    stored_cookie, updated_at = _read_stored_cookie()
    if stored_cookie and not _is_expired(updated_at):
        _clear_reauth_needed()
        return stored_cookie

    # Priority 3: refresh via Playwright
    if stored_cookie and _is_expired(updated_at):
        logger.info("LinkedIn cookie expired (>%d days) — refreshing...", COOKIE_MAX_AGE_DAYS)
    else:
        logger.info("No LinkedIn cookie found — launching browser for login...")

    fresh_cookie = _extract_li_at_from_playwright()
    if fresh_cookie:
        _save_cookie(fresh_cookie)
        return fresh_cookie

    # All failed — return whatever we had (may be stale but worth trying)
    if stored_cookie:
        logger.warning("Cookie refresh failed — using possibly stale cookie")
        return stored_cookie

    return ""
