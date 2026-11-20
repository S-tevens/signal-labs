from __future__ import annotations

import json

from .. import mapping


def detect(line: str) -> bool:
    return line.lstrip().startswith("{")


def parse_many(line: str) -> list[dict]:
    """NDJSON: one object per line. Field names, units and time formats come from mapping.yaml; other fields are dropped."""
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return mapping.get().normalize_nested(data, line)


def parse(line: str) -> dict:
    return parse_many(line)[0]
