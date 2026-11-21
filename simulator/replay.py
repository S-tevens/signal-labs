"""Replay and scripted timelines (E17).

    python simulator/replay.py build simulator/timelines/demo.json -o data/demo.stream.jsonl
    python simulator/replay.py play  simulator/timelines/demo.json              # build and play, real time
    python simulator/replay.py play  data/demo.stream.jsonl --speed 5           # five times faster
    python simulator/replay.py play  some.log                                   # a recorded log with ISO timestamps

A timeline (JSON) scripts what the organizers' injections look like: steady traffic, a CPU spike, a latency spike, a
failed-login burst and a SaaS outage. Building one is deterministic: the same timeline and seed always give the same
recording, byte for byte. A recording is NDJSON, one object per line:
    {"t": 12.0, "line": "ts=@T@ host=web-1 metric=cpu_pct value=35.2"}      send this line at offset t
    {"t": 230.0, "action": "link", "state": "down"}                          cut or restore the collector's SaaS link
`@T@` becomes the event time at play: now plus the offset (divided by --speed), so data is always live, never backdated.
A raw log file also plays: ISO-8601 timestamps in it set the offsets and are rebased to now. (Epoch or other time
formats in a raw log are not rebased; use a recording for those.)

Environment: COLLECTOR_URL (default http://127.0.0.1:8101).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error, request

COLLECTOR = os.getenv("COLLECTOR_URL", "http://127.0.0.1:8101").rstrip("/")
ISO = re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?")

# metric -> (mean, spread) of the steady baseline
BASELINE = {
    "cpu_pct": (35, 5), "mem_pct": (55, 4), "bandwidth_mbps": (120, 25), "latency_ms": (40, 6),
    "disk_pct": (48, 1.5), "packet_loss_pct": (0.1, 0.08), "service_up": (1, 0),
}
SPIKE_METRIC = {"cpu_spike": "cpu_pct", "latency_spike": "latency_ms", "packet_loss_spike": "packet_loss_pct", "disk_fill": "disk_pct"}


def build(timeline: dict) -> list[dict]:
    """Timeline -> recording. Pure and deterministic."""
    rng = random.Random(timeline.get("seed", 0))
    length, step = float(timeline.get("length_s", 300)), float(timeline.get("step_s", 2))
    hosts = timeline.get("hosts", ["web-1"])
    steps = timeline.get("steps", [])
    rows: list[dict] = []
    t = 0.0
    while t < length:
        for hi, host in enumerate(hosts):
            for mi, (metric, (mean, spread)) in enumerate(BASELINE.items()):
                value = rng.gauss(mean, spread)  # always drawn, so a spike never shifts later values
                for s in steps:
                    if SPIKE_METRIC.get(s["do"]) == metric and s.get("host") == host and s["at"] <= t < s["at"] + s.get("for", step):
                        value = float(s["value"])
                if not any(s["do"] == "steady" and s["at"] <= t < s["at"] + s.get("for", length) for s in steps):
                    continue
                value = 1 if metric == "service_up" else round(max(0.0, value), 2)
                if (hi + mi) % 2:
                    line = json.dumps({"kind": "metric", "ts": "@T@", "host": host, "name": metric, "value": value}, sort_keys=True)
                else:
                    line = f"ts=@T@ host={host} metric={metric} value={value}"
                rows.append({"t": t, "line": line})
        t += step
    for s in steps:
        if s["do"] == "failed_logins":
            for i in range(int(s.get("count", 30))):
                rows.append({"t": float(s["at"]), "line": f'ts=@T@ host={s["host"]} msg="Failed password for root from 203.0.113.{i % 250 + 1} port 22"'})
        elif s["do"] == "outage":
            rows.append({"t": float(s["at"]), "action": "link", "state": "down"})
            rows.append({"t": float(s["at"]) + float(s.get("for", 20)), "action": "link", "state": "up"})
    rows.sort(key=lambda r: r["t"])  # stable: same-offset rows keep their order
    return rows


def import_log(text: str) -> list[dict]:
    """A raw log with ISO timestamps -> recording, offsets from the first timestamp, timestamps replaced by @T@."""
    rows, first, last = [], None, 0.0
    for line in text.splitlines():
        if not line.strip():
            continue
        m = ISO.search(line)
        if m:
            raw = m.group(0).replace(" ", "T", 1)
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            epoch = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
            first = epoch if first is None else first
            last = max(0.0, epoch - first)
            line = line[: m.start()] + "@T@" + line[m.end():]
        rows.append({"t": round(last, 3), "line": line})
    return rows


def dump(rows: list[dict]) -> str:
    return "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"


def load(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    first = text.lstrip()[:1]
    if path.suffix == ".json" or (first == "{" and '"steps"' in text[:2000]):
        return build(json.loads(text))
    head = text.splitlines()[0] if text.strip() else ""
    if head.startswith("{") and '"t"' in head and ('"line"' in head or '"action"' in head):
        return [json.loads(x) for x in text.splitlines() if x.strip()]
    return import_log(text)


def _post(path: str, data: bytes = b"", headers: dict | None = None) -> bool:
    try:
        with request.urlopen(request.Request(f"{COLLECTOR}{path}", data=data, headers=headers or {}, method="POST"), timeout=10):
            return True
    except (error.URLError, OSError):
        return False


def _auth() -> dict:
    """The push token, when the collector was started with -AcceptPush."""
    token = os.getenv("INGEST_TOKEN", "")
    f = Path(__file__).resolve().parents[1] / "data" / "ingest.token"
    if not token and f.exists():
        token = f.read_text(encoding="ascii").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def play(rows: list[dict], speed: float = 1.0, log=print) -> dict:
    start = time.time()
    sent = failed = 0
    i = 0
    while i < len(rows):
        offset = rows[i]["t"]
        batch = []
        while i < len(rows) and rows[i]["t"] == offset:
            batch.append(rows[i])
            i += 1
        delay = start + offset / speed - time.time()
        if delay > 0:
            time.sleep(delay)
        stamp = (datetime.fromtimestamp(start + offset / speed, timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [r["line"].replace("@T@", stamp) for r in batch if "line" in r]
        if lines:
            ok = _post("/ingest", "\n".join(lines).encode(), _auth())
            sent, failed = sent + (len(lines) if ok else 0), failed + (0 if ok else len(lines))
        for r in batch:
            if r.get("action") == "link":
                log(f"  t={offset:.0f}s: SaaS link {r['state']}")
                _post(f"/local/saas-link/{r['state']}")
    return {"lines_sent": sent, "lines_failed": failed, "seconds": round(time.time() - start, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["build", "play"])
    ap.add_argument("source", help="timeline .json, recording .jsonl or raw log")
    ap.add_argument("-o", "--out", help="build: where to write the recording")
    ap.add_argument("--speed", type=float, default=1.0, help="play: 5 means five times faster")
    args = ap.parse_args()
    rows = load(Path(args.source))
    if args.command == "build":
        text = dump(rows)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"wrote {len(rows)} rows to {args.out}")
        else:
            sys.stdout.write(text)
        return 0
    if args.speed <= 0:
        print("--speed must be positive")
        return 2
    length = rows[-1]["t"] / args.speed if rows else 0
    print(f"playing {len(rows)} rows over about {length:.0f} s into {COLLECTOR} ...")
    try:
        result = play(rows, args.speed)
    finally:
        _post("/local/saas-link/up")  # never leave the link cut if interrupted
    print(result)
    return 0 if not result["lines_failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
