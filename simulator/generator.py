"""Telemetry simulator: feeds a collector in several formats, with optional scenarios.

Usage (from the repo root):
    python simulator/generator.py --url http://localhost:8101/ingest --seconds 30
    python simulator/generator.py --scenario secret
    python simulator/generator.py --scenario failed-logins --count 40
    python simulator/generator.py --scenario cpu-spike

Replace or extend with the organizer stream once its format is published
(add a parser in collector/parsers/; this file does not need to change).
"""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone
from urllib import request

HOSTS = ["web-1", "web-2", "db-1", "router-1"]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def steady_lines() -> list[str]:
    lines = []
    for host in HOSTS:
        cpu = random.gauss(35, 5)
        lat = random.gauss(40, 6)
        # same data in three different formats on purpose: the collector must handle any
        lines.append(json.dumps({"kind": "metric", "ts": now(), "tz": "Asia/Kolkata", "host": host, "name": "cpu_pct", "value": round(cpu, 1)}))
        lines.append(f"ts={now()} host={host} metric=latency_ms value={lat:.1f}")
        lines.append(json.dumps({"kind": "metric", "ts": now(), "host": host, "name": "mem_pct", "value": round(random.gauss(55, 4), 1)}))
    return lines


def scenario_lines(name: str, count: int) -> list[str]:
    if name == "secret":
        return [
            "Nov 20 09:15:01 web-1 app[311]: user alice@corp.com logged in from 10.2.4.7 password=Hunter2! token=abc123def456",
            "Nov 20 09:15:02 web-1 app[311]: using key AKIAABCDEFGHIJKLMNOP and Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghijk",
        ]
    if name == "failed-logins":
        return [f"Nov 20 09:16:{i % 60:02d} web-1 sshd[88]: Failed password for root from 203.0.113.{i % 250 + 1}" for i in range(count)]
    if name == "cpu-spike":
        return [json.dumps({"kind": "metric", "ts": now(), "host": "web-1", "name": "cpu_pct", "value": round(random.gauss(97, 1), 1)}) for _ in range(count)]
    if name == "latency":
        return [f"ts={now()} host=router-1 metric=latency_ms value={random.gauss(600, 40):.1f}" for _ in range(count)]
    raise SystemExit(f"unknown scenario: {name}")


def send(url: str, lines: list[str]) -> str:
    req = request.Request(url, data="\n".join(lines).encode(), method="POST")
    with request.urlopen(req, timeout=5) as resp:
        return resp.read().decode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8101/ingest")
    ap.add_argument("--seconds", type=int, default=0, help="stream steady telemetry for N seconds")
    ap.add_argument("--scenario", choices=["secret", "failed-logins", "cpu-spike", "latency"])
    ap.add_argument("--count", type=int, default=30)
    args = ap.parse_args()

    if args.scenario:
        print(send(args.url, scenario_lines(args.scenario, args.count)))
    end = time.time() + args.seconds
    while time.time() < end:
        print(send(args.url, steady_lines()))
        time.sleep(2)


if __name__ == "__main__":
    main()
