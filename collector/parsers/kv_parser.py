from __future__ import annotations

import re

from .. import mapping

_PAIR = re.compile(r'(\w+)=("[^"]*"|\S+)')


def detect(line: str) -> bool:
    return len(_PAIR.findall(line)) >= 2


def parse_many(line: str) -> list[dict]:
    fields = {k: v.strip('"') for k, v in _PAIR.findall(line)}
    records = mapping.get().normalize(fields, line)
    for r in records:
        if r["kind"] == "log" and not fields.get("msg") and not fields.get("message"):
            r["message"] = line  # a log line keeps its whole text locally
    return records


def parse(line: str) -> dict:
    return parse_many(line)[0]
