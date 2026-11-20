from __future__ import annotations

import re

# RFC3164-style: optional <PRI>, "Mon DD HH:MM:SS host proc[pid]: message"
_RE = re.compile(r"^(?:<\d+>)?([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+([^\s:]+?)(?:\[\d+\])?:\s*(.*)$")


def detect(line: str) -> bool:
    return _RE.match(line) is not None


def parse(line: str) -> dict:
    m = _RE.match(line)
    assert m is not None
    _stamp, host, _proc, message = m.groups()
    # RFC3164 timestamps carry no year or zone, so we do not trust them: ts stays None
    # and the pipeline stamps arrival time in UTC. Known limitation (see docs).
    return {"kind": "log", "ts": None, "host": host, "message": message}
