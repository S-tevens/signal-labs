"""InfluxDB line protocol: `measurement,tag=v,tag2=v2 field=1.5,other=3i 1700000000000000000` (Telegraf output and many agents)."""
from __future__ import annotations

import re

from .. import mapping

# The measurement may not contain "=": that is what tells this apart from a key=value log line.
_RE = re.compile(r"^([^\s,=]+)((?:,[^\s,=]+=[^\s,]+)*)\s+([^\s=,]+=[^\s,]+(?:,[^\s=,]+=[^\s,]+)*)(?:\s+(\d{9,19}))?\s*$")
_HOSTS = ("host", "hostname", "node", "instance", "server")


def detect(line: str) -> bool:
    return _RE.match(line.strip()) is not None


def _number(raw: str):
    raw = raw.strip().rstrip("i")
    if raw.lower() in ("true", "t"):
        return 1
    if raw.lower() in ("false", "f"):
        return 0
    return raw.strip('"')


def parse_many(line: str) -> list[dict]:
    m = _RE.match(line.strip())
    assert m is not None
    measurement, tag_text, field_text, stamp = m.groups()
    tags = dict(t.split("=", 1) for t in tag_text.split(",") if "=" in t)
    row: dict = {"host": next((tags[k] for k in _HOSTS if tags.get(k)), "unknown")}
    if stamp:
        row["ts"] = stamp  # nanoseconds by default; the mapping works out the unit from the size
    for part in field_text.split(","):
        key, _, raw = part.partition("=")
        value = _number(raw)
        row[key] = value
        row[f"{measurement}_{key}"] = value  # `cpu_usage_idle` as well as `usage_idle`
    return mapping.get().normalize(row, line)


def parse(line: str) -> dict:
    return parse_many(line)[0]
