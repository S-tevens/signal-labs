"""The collector's own, local health verdict for a payload (E23): same thresholds and rules as the platform."""
from __future__ import annotations

from pathlib import Path

import yaml

_RULES: dict | None = None


def rules() -> dict:
    global _RULES
    if _RULES is None:
        _RULES = yaml.safe_load(Path(__file__).with_name("health.yaml").read_text(encoding="utf-8"))["metrics"]
    return _RULES


def metric_state(name: str, value: float) -> str:
    r = rules().get(name)
    if not r:
        return "Excellent"  # no threshold for this metric (for example bandwidth), same as the platform
    if r.get("inverse"):
        return "Poor" if value <= r["poor"] else "Fair" if value <= r["fair"] else "Good" if value < r["good"] else "Excellent"
    return "Poor" if value >= r["poor"] else "Fair" if value >= r["fair"] else "Good" if value >= r["good"] else "Excellent"


def event_state(severity: str) -> str:
    """Critical events are Poor, high ones Fair, the rest carry no health signal (the platform's own rule)."""
    return "Poor" if severity == "critical" else "Fair" if severity in ("high", "error") else "Good"
