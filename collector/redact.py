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


RULE_NAMES = frozenset(name for name, _ in PATTERNS)


def redact(text: str, rules: "list[str] | None" = None) -> tuple[str, list[str]]:
    """Return (scrubbed_text, names_of_rules_that_fired). `rules` limits which rules run (default: all)."""
    fired: list[str] = []
    for name, pattern in PATTERNS:
        if rules is not None and name not in rules:
            continue
        text, n = pattern.subn(f"[REDACTED:{name}]", text)
        if n:
            fired.append(name)
    return text, fired


def find_spans(text: str, rules: "list[str] | None" = None) -> list[dict]:
    """Where in `text` each scrubbing rule matched, as non-overlapping {start, end, rule} spans.

    The local egress panel uses this to highlight what was sensitive in a raw record. Overlaps (an IP inside a
    password value, say) are merged into one span labelled with the rule that matched first.
    """
    raw: list[dict] = []
    for name, pattern in PATTERNS:
        if rules is not None and name not in rules:
            continue
        raw.extend({"start": m.start(), "end": m.end(), "rule": name} for m in pattern.finditer(text))
    raw.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    merged: list[dict] = []
    for span in raw:
        if merged and span["start"] < merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], span["end"])
        else:
            merged.append(dict(span))
    return merged


def pseudonym(value: str, secret: str) -> str:
    """Stable, non-reversible source id: HMAC with a secret that never leaves the collector."""
    digest = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return "src_" + digest[:12]
