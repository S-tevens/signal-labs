"""Five differently shaped sample streams (E16), all stamped "now", to show a new format needs mapping, not code.

    python simulator/samples.py --list
    python simulator/samples.py wide-ndjson | python simulator/generator.py ...   (or POST the lines to /ingest)

Each function returns lines. Together they cover: epoch milliseconds, ratios and seconds needing unit conversion,
a CSV header with a day-first date format, other field names (instance, measurement), RFC3164 syslog, plain text, and
unknown fields that must be dropped.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

HOSTS = ["edge-1", "edge-2"]


def wide_ndjson(now: float | None = None) -> list[str]:
    """Epoch milliseconds, other field names, a metric per column, ratio and seconds units, plus unknown fields."""
    t = now or time.time()
    return [
        json.dumps({"timestamp": int(t * 1000), "hostname": h, "cpu_ratio": 0.42, "mem_free_pct": 38.0, "latency_s": 0.045,
                    "rack": "r7", "owner": "payments-team", "api_token": "tok_live_should_never_travel"})
        for h in HOSTS
    ]


def csv_with_header(now: float | None = None) -> list[str]:
    t = datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%d/%m/%Y %H:%M:%S")
    rows = ["time,node,measurement,reading"]
    for h in HOSTS:
        rows += [f"{t},{h},cpu,61.5", f"{t},{h},bandwidth_kbps,88000", f"{t},{h},packet_loss_ratio,0.002"]
    return rows


def key_value(now: float | None = None) -> list[str]:
    t = datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [f"ts={t} instance={h} measurement=disk_used_pct value=71.2 site=mumbai" for h in HOSTS] + [
        f"ts={t} instance={h} measurement=up value=1" for h in HOSTS
    ]


def syslog_logins(now: float | None = None) -> list[str]:
    stamp = datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%b %d %H:%M:%S")
    return [f"<38>{stamp} edge-1 sshd[411]: Failed password for root from 203.0.113.{i + 1} port 22 ssh2" for i in range(12)]


def mixed_text(now: float | None = None) -> list[str]:
    t = datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return [
        f"{t} edge-1 backup finished for user alice@corp.com using token=abc123def456",
        json.dumps({"@timestamp": t, "host": "edge-2", "kind": "log", "message": "service restarted, api_key=sk_live_abcdef123456", "pod": "x-9"}),
        "free text with no structure at all but password=Hunter2!",
    ]


SAMPLES = {
    "wide-ndjson": wide_ndjson,
    "csv-header": csv_with_header,
    "key-value-aliases": key_value,
    "syslog-logins": syslog_logins,
    "mixed-text": mixed_text,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("--list", "-l") or sys.argv[1] not in SAMPLES:
        print("samples:", ", ".join(SAMPLES))
    else:
        print("\n".join(SAMPLES[sys.argv[1]]()))
