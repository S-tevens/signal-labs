"""Local secret scrubbing and pseudonymization.

This is the FIRST gate. The allow-list schema (schema.py) is the second, independent gate.
Regex scrubbing can miss novel secret formats; that is why free text never travels in a payload.
"""
from __future__ import annotations

import hashlib
import hmac
import re

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    ("password", re.compile(r"(?i)\b(pass(?:word|wd)?|pwd)\s*[=:]\s*\S+")),
    ("token", re.compile(r"(?i)\b(token|secret|api[_-]?key|apikey)\s*[=:]\s*\S+")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Return (scrubbed_text, names_of_rules_that_fired)."""
    fired: list[str] = []
    for name, pattern in PATTERNS:
        text, n = pattern.subn(f"[REDACTED:{name}]", text)
        if n:
            fired.append(name)
    return text, fired


def pseudonym(value: str, secret: str) -> str:
    """Stable, non-reversible source id: HMAC with a secret that never leaves the collector."""
    digest = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return "src_" + digest[:12]
