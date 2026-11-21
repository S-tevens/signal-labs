from __future__ import annotations

import re

# RFC3164-style: optional <PRI>, "Mon DD HH:MM:SS host proc[pid]: message"
_RE = re.compile(r"^(?:<\d+>)?([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+([^\s:]+?)(?:\[\d+\])?:\s*(.*)$")
# RFC5424: "<PRI>1 TIMESTAMP HOST APP PROCID MSGID [STRUCTURED-DATA] message" (the time has a year and a zone, so it is trusted)
_RE5424 = re.compile(r"^<\d+>1\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(?:-|\[.*?\](?=\s|$))*\s*(.*)$")


def detect(line: str) -> bool:
    return _RE.match(line) is not None or _RE5424.match(line) is not None


def parse(line: str) -> dict:
    five = _RE5424.match(line)
    if five:
        stamp, host, _app, _proc, _msgid, message = five.groups()
        return {"kind": "log", "ts": None if stamp == "-" else stamp, "host": host if host != "-" else "unknown", "message": message}
    m = _RE.match(line)
    assert m is not None
    _stamp, host, _proc, message = m.groups()
    # RFC3164 timestamps carry no year or zone, so we do not trust them: ts stays None
    # and the pipeline stamps arrival time in UTC. Known limitation (see docs).
    return {"kind": "log", "ts": None, "host": host, "message": message}
