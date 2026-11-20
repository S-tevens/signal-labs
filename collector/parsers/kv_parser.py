from __future__ import annotations

import re

_PAIR = re.compile(r'(\w+)=("[^"]*"|\S+)')


def detect(line: str) -> bool:
    return len(_PAIR.findall(line)) >= 2


def parse(line: str) -> dict:
    fields = {k: v.strip('"') for k, v in _PAIR.findall(line)}
    kind = "metric" if "metric" in fields and "value" in fields else "log"
    return {
        "kind": kind,
        "ts": fields.get("ts"),
        "tz": fields.get("tz"),
        "host": fields.get("host", "unknown"),
        "name": fields.get("metric"),
        "value": fields.get("value"),
        "message": fields.get("msg") or line,
    }
