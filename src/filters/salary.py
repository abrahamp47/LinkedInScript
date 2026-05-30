"""Salary parsing and filtering for LinkedInScript.

Handles all common Indian salary formats:
- Monthly: "30,000/month", "Rs. 45,000/month"
- K-suffix: "30K/mo", "30K"
- LPA: "3.6 LPA", "3.6 lpa", "4.8 LPA"
- L/yr: "3.6L/yr"
- Lakh/lac/lakhs: "6 lakh per annum", "6 lakhs p.a.", "3 lac per annum"
- Ranges: "3-5 LPA" (lower bound), "25,000 - 45,000/month" (lower bound)
- Currency prefix: "INR 30,000", "Rs 30000"
- Bare numbers: "45000" (assume monthly if >= 5000)

Exports:
    parse_salary_to_monthly(salary_str) -> int | None
    filter_by_salary(jobs, min_salary_monthly, respect_watchlist) -> tuple[list, list]
"""

import logging
import re

from src.models import Job

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled regex patterns (all use re.IGNORECASE)
# Order matters: first match wins.
# ---------------------------------------------------------------------------

# Pattern A - RANGE with LPA/L variants: "3-5 LPA", "3-5 L.P.A."
PATTERN_RANGE_LPA = re.compile(
    r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*(?:lpa|l\.?p\.?a\.?|l/yr|lakhs?\s*(?:per\s*annum|p\.?a\.?|pa))",
    re.IGNORECASE,
)

# Pattern B - RANGE with monthly: "25,000 - 45,000/month"
PATTERN_RANGE_MONTHLY = re.compile(
    r"(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)\s*/?\s*(?:month|mo|per\s*month|pm)",
    re.IGNORECASE,
)

# Pattern C - LPA/L.P.A/L/yr: "3.6 LPA", "3.6L/yr"
PATTERN_LPA = re.compile(
    r"(\d+\.?\d*)\s*(?:lpa|l\.?p\.?a\.?|l/yr)",
    re.IGNORECASE,
)

# Pattern D - Lakh/lac variants with per annum: "6 lakh per annum", "3 lac p.a."
PATTERN_LAKH = re.compile(
    r"(\d+\.?\d*)\s*(?:lacs?|lakhs?)\s*(?:per\s*annum|p\.?a\.?|pa|per\s*year|/yr)",
    re.IGNORECASE,
)

# Pattern E - K-suffix with monthly indicator: "30K/mo", "30K/month"
PATTERN_K_MONTHLY = re.compile(
    r"(\d+\.?\d*)\s*k\s*/?\s*(?:mo|month|per\s*month|pm)",
    re.IGNORECASE,
)

# Pattern F - K-suffix alone (no monthly indicator): "30K"
PATTERN_K_ALONE = re.compile(
    r"(\d+\.?\d*)\s*k\b",
    re.IGNORECASE,
)

# Pattern G - Explicit monthly with optional currency: "INR 30,000/month", "Rs. 45,000/mo"
PATTERN_CURRENCY_MONTHLY = re.compile(
    r"(?:inr|rs\.?|₹)\s*(\d[\d,]*)\s*/?\s*(?:mo|month|per\s*month|pm)",
    re.IGNORECASE,
)

# Pattern G2 - Plain number with monthly indicator (no currency): "30,000/month", "45000/mo"
PATTERN_PLAIN_MONTHLY = re.compile(
    r"(\d[\d,]*)\s*/?\s*(?:month|mo|per\s*month|pm)\b",
    re.IGNORECASE,
)

# Pattern H - Currency-prefixed bare number: "INR 30,000", "Rs 30000"
PATTERN_CURRENCY_BARE = re.compile(
    r"(?:inr|rs\.?|₹)\s*(\d[\d,]*)",
    re.IGNORECASE,
)

# Pattern I - Bare number: "45000"
PATTERN_BARE_NUMBER = re.compile(
    r"^\s*(\d[\d,]*)\s*$",
)

# Minimum threshold for bare numbers to be considered salary (not an ID or code)
BARE_NUMBER_MIN_THRESHOLD = 5000


def parse_salary_to_monthly(salary_str: str | None) -> int | None:
    """Parse an Indian salary string to monthly INR amount.

    Args:
        salary_str: Raw salary string from job listing, or None.

    Returns:
        Monthly salary as int, or None if unparseable/missing.
    """
    # None/empty guard
    if salary_str is None or salary_str.strip() == "":
        return None

    text = salary_str.strip()

    # Pattern A - Range with LPA/L variants
    match = PATTERN_RANGE_LPA.search(text)
    if match:
        lower = float(match.group(1))
        return int(round(lower * 100000 / 12))

    # Pattern B - Range with monthly
    match = PATTERN_RANGE_MONTHLY.search(text)
    if match:
        lower = int(match.group(1).replace(",", ""))
        return lower

    # Pattern C - LPA/L.P.A/L/yr
    match = PATTERN_LPA.search(text)
    if match:
        value = float(match.group(1))
        return int(round(value * 100000 / 12))

    # Pattern D - Lakh/lac variants with per annum
    match = PATTERN_LAKH.search(text)
    if match:
        value = float(match.group(1))
        return int(round(value * 100000 / 12))

    # Pattern E - K-suffix with monthly indicator
    match = PATTERN_K_MONTHLY.search(text)
    if match:
        value = float(match.group(1))
        return int(round(value * 1000))

    # Pattern F - K-suffix alone
    match = PATTERN_K_ALONE.search(text)
    if match:
        value = float(match.group(1))
        return int(round(value * 1000))

    # Pattern G - Currency prefixed monthly
    match = PATTERN_CURRENCY_MONTHLY.search(text)
    if match:
        value = int(match.group(1).replace(",", ""))
        return value

    # Pattern G2 - Plain number with monthly indicator
    match = PATTERN_PLAIN_MONTHLY.search(text)
    if match:
        value = int(match.group(1).replace(",", ""))
        return value

    # Pattern H - Currency prefixed bare number
    match = PATTERN_CURRENCY_BARE.search(text)
    if match:
        value = int(match.group(1).replace(",", ""))
        return value

    # Pattern I - Bare number
    match = PATTERN_BARE_NUMBER.match(text)
    if match:
        value = int(match.group(1).replace(",", ""))
        if value >= BARE_NUMBER_MIN_THRESHOLD:
            return value
        return None

    # No pattern matched
    return None


def filter_by_salary(
    jobs: list[Job],
    min_salary_monthly: int,
    respect_watchlist: bool = True,
) -> tuple[list[Job], list[Job]]:
    """Filter jobs by minimum monthly salary.

    Args:
        jobs: List of Job instances to filter.
        min_salary_monthly: Minimum acceptable monthly salary in INR.
        respect_watchlist: If True, watchlist-matched jobs bypass salary filter (D-09).

    Returns:
        Tuple of (passed, rejected) job lists.
    """
    passed: list[Job] = []
    rejected: list[Job] = []

    for job in jobs:
        # None/empty guard: missing salary = pass (D-08)
        if job.salary is None or job.salary.strip() == "":
            passed.append(job)
            continue

        # Watchlist bypass (D-09)
        if respect_watchlist and job.watchlist_match:
            passed.append(job)
            continue

        # Parse salary
        parsed = parse_salary_to_monthly(job.salary)

        # Unparseable = treat as missing (conservative default)
        if parsed is None:
            passed.append(job)
            continue

        # Compare against minimum
        if parsed < min_salary_monthly:
            logger.debug(
                "Rejected: %s @ %s -- salary below minimum (%d < %d)",
                job.title,
                job.company,
                parsed,
                min_salary_monthly,
            )
            rejected.append(job)
        else:
            passed.append(job)

    return passed, rejected
