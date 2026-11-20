"""Prometheus text exposition: `name{label="value",...} 12.5 [timestamp]` (what /metrics endpoints and exporters serve)."""
from __future__ import annotations

import re

from .. import mapping

_RE = re.compile(r"^([A-Za-z_:][\w:]*)(\{[^}]*\})?\s+([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|NaN|[-+]?Inf)(?:\s+(\d{9,19}))?\s*$")
_LABEL = re.compile(r'([A-Za-z_]\w*)\s*=\s*"((?:[^"\\]|\\.)*)"')
_HOSTS = ("instance", "host", "hostname", "node", "nodename", "pod", "kubernetes_node")


def detect(line: str) -> bool:
    return not line.startswith("#") and _RE.match(line.strip()) is not None


def parse_many(line: str) -> list[dict]:
    m = _RE.match(line.strip())
    assert m is not None
    name, labels_text, value, stamp = m.groups()
    labels = dict(_LABEL.findall(labels_text or ""))
    host = next((labels[k] for k in _HOSTS if labels.get(k)), "unknown")
    if host != "unknown" and ":" in host and not host.count(":") > 1:  # instance="web-1:9100" -> web-1
        host = host.rsplit(":", 1)[0]
    row = {"host": host, "metric": name, "value": value}
    if stamp:
        row["ts"] = stamp  # milliseconds in Prometheus; the mapping tells seconds, ms, us and ns apart by size
    return mapping.get().normalize(row, line)


def parse(line: str) -> dict:
    return parse_many(line)[0]
