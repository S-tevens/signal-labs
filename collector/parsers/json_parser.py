from __future__ import annotations

import json


def detect(line: str) -> bool:
    return line.lstrip().startswith("{")


def parse(line: str) -> dict:
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    kind = data.get("kind") or ("metric" if "metric" in data or "name" in data else "log")
    return {
        "kind": kind,
        "ts": data.get("ts"),
        "tz": data.get("tz"),
        "host": data.get("host", "unknown"),
        "name": data.get("metric") or data.get("name"),
        "value": data.get("value"),
        "message": data.get("message") or data.get("msg") or "",
    }
