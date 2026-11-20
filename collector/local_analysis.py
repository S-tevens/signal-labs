"""Local analysis: turn raw log activity into a security summary without exporting any raw record.

Only counts and a category leave the environment. Usernames, IPs and message text stay local.
Known limitation: detection is per fixed window, so a slow trickle spread thinly across many
windows (below the threshold in each) is reported as individual warnings, not as one burst.
"""
from __future__ import annotations

import re

AUTH_FAIL = re.compile(r"(?i)(failed password|authentication failure|invalid (user|password)|login failed)")

# Template text. Raw message text has no path into the payload.
SUMMARY = {
    "auth_failure_burst": "repeated failed logins",
    "auth_failure": "failed login observed",
    "log_event": "log events observed",
}


def is_auth_failure(message: str) -> bool:
    return bool(AUTH_FAIL.search(message or ""))


def classify_auth(count: int, threshold: int) -> tuple[str, str]:
    """Return (category, severity) for `count` failed logins from one source in one window."""
    if count >= 5 * threshold:
        return "auth_failure_burst", "critical"
    if count >= threshold:
        return "auth_failure_burst", "high"
    return "auth_failure", "warning"
