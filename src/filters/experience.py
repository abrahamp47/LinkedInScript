from __future__ import annotations

"""Experience level filter — ensures only intern/entry-level roles pass through.

LinkedIn's job_type=internship filter is imprecise and often returns senior roles
that happen to mention "intern" in the description or contain intern keywords.

This filter rejects jobs whose titles clearly indicate non-intern seniority.
"""

import re

from src.models import Job

# Patterns that indicate senior/non-intern roles (case-insensitive)
SENIOR_TITLE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\blead\b",
    r"\bprincipal\b",
    r"\bstaff\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bvp\b",
    r"\bhead of\b",
    r"\barchitect\b",
    # Numbered roles: Engineer II, SDE 3, Software Engr II, Apps 3, L3
    r"\b\w+\s+(?:II|III|IV)\b",
    r"\b(?:sde|swe|software|developer|engr?|engineer|specialist|apps?)\s*[2-9]\b",
    r"\blevel\s*[3-9]\b",
    r"\bL[3-9]\b",
    r"\b(?:5|6|7|8|9|10)\+?\s*(?:years?|yrs?)\b",
    r"\bexperienced\b",
]

# Patterns that confirm intern/entry-level (if present, always pass)
INTERN_TITLE_PATTERNS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\btrainee\b",
    r"\bapprentice\b",
    r"\bfresher\b",
    r"\bgraduate\s*(?:engineer|trainee|hire)\b",
    r"\bentry\s*level\b",
    r"\bjunior\b",
    r"\bassociate\b(?!\s*director|\s*vp)",
]

_senior_regex = re.compile("|".join(SENIOR_TITLE_PATTERNS), re.IGNORECASE)
_intern_regex = re.compile("|".join(INTERN_TITLE_PATTERNS), re.IGNORECASE)

# Description patterns that indicate too much experience required
EXPERIENCE_REQUIRED_PATTERNS = [
    r"\b(?:3|4|5|6|7|8|9|10)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)\b",
    r"\bminimum\s*(?:3|4|5|6|7|8|9|10)\s*(?:years?|yrs?)\b",
    r"\b(?:at\s*least|atleast)\s*(?:3|4|5|6|7|8|9|10)\s*(?:years?|yrs?)\b",
    r"\bexperience:\s*(?:3|4|5|6|7|8|9|10)\+?\s*(?:years?|yrs?)\b",
]

# Description patterns that confirm intern/fresher-friendly
INTERN_FRIENDLY_PATTERNS = [
    r"\b(?:0|zero|no)\s*(?:years?|yrs?)?\s*(?:of\s*)?experience\b",
    r"\bfresher\b",
    r"\bfresh\s*graduate\b",
    r"\bcurrently\s*(?:pursuing|enrolled|studying)\b",
    r"\bstudent\b",
    r"\b(?:final|last)\s*year\b",
    r"\bno\s*(?:prior\s*)?experience\s*(?:required|needed)\b",
    r"\b(?:currently|pursuing)\s*(?:b\.?tech|b\.?e|bca|mca|m\.?tech|m\.?s|bachelor|master)\b",
    r"\b(?:0-1|0-2|1-2)\s*(?:years?|yrs?)\b",
]

_exp_required_regex = re.compile("|".join(EXPERIENCE_REQUIRED_PATTERNS), re.IGNORECASE)
_intern_friendly_regex = re.compile("|".join(INTERN_FRIENDLY_PATTERNS), re.IGNORECASE)


def filter_by_experience(jobs: list[Job]) -> tuple[list[Job], list[Job]]:
    """Filter out jobs with senior/non-intern titles or high experience requirements.

    Logic:
    1. Title check:
       - If title matches an intern pattern -> always pass
       - If title matches a senior pattern and NOT intern -> reject
    2. Description check (for jobs that passed title check):
       - If description mentions intern-friendly signals -> pass
       - If description requires 3+ years experience -> reject
       - If neither -> pass (ambiguous is kept, better to over-include)

    Args:
        jobs: List of Job instances.

    Returns:
        Tuple of (passed_jobs, rejected_jobs).
    """
    passed = []
    rejected = []

    for job in jobs:
        title = job.title or ""
        description = job.description or ""

        # Title-level check first
        if _intern_regex.search(title):
            passed.append(job)
            continue

        if _senior_regex.search(title):
            rejected.append(job)
            continue

        # Description-level check for ambiguous titles
        if _intern_friendly_regex.search(description):
            passed.append(job)
        elif _exp_required_regex.search(description):
            rejected.append(job)
        else:
            passed.append(job)

    return passed, rejected
