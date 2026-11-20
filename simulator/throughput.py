"""Measured throughput on one machine: SaaS signed ingest and collector line intake.

Run with the stack up: SAAS_URL=https://127.0.0.1:8080 SAAS_CA_FILE=data/certs/ca.pem python simulator/throughput.py
Simulator data over loopback; see docs/p4/scale-and-production.md for caveats.
"""
from __future__ import annotations

import os
import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenarios as sc  # noqa: E402

N_PAYLOADS = int(os.getenv("N_PAYLOADS", "10000"))
BATCH = 500
N_LINES = int(os.getenv("N_LINES", "20000"))
CHUNK = 2000


def pct(vals, p):
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * p / 100))]


def saas_ingest():
    sources = ["src_" + uuid.uuid4().hex[:8] for _ in range(50)]
    base = time.time() - 600
    payloads = [{"payload_id": str(uuid.uuid4()), "tenant_ref": "t-acme", "collector_id": "col-blr-01",
                 "source_id": sources[i % 50], "region": "in", "event_ts_utc": sc.iso(base + i * 0.05),
                 "source_tz": "UTC", "window_s": 5, "metric": {"name": "cpu_pct", "value": 30.0, "unit": "%"},
                 "health_state": "Excellent", "collector_version": "1.0.0"} for i in range(N_PAYLOADS)]
    lat, accepted, failed = [], 0, 0
    t0 = time.perf_counter()
    for i in range(0, len(payloads), BATCH):
        batch = payloads[i:i + BATCH]
        r0 = time.perf_counter()
        code, body = sc.saas_post_signed(batch)
        lat.append((time.perf_counter() - r0) * 1000)
        if code == 200:
            acc = body.get("accepted", len(batch)) if isinstance(body, dict) else len(batch)
            accepted += len(acc) if isinstance(acc, list) else acc
        else:
            failed += 1
            print(f"  request failed: HTTP {code} {str(body)[:120]}")
    wall = time.perf_counter() - t0
    time.sleep(2)
    sample = random.sample([p["payload_id"] for p in payloads], 20)
    found = sum(1 for pid in sample if sc._call(f"{sc.SAAS}/v1/objects/observation/{pid}", headers={"Authorization": f"Bearer {sc.DASH}"})[0] == 200)
    return dict(sent=N_PAYLOADS, accepted=accepted, failed=failed, pps=N_PAYLOADS / wall, wall=wall,
                p50=pct(lat, 50), p95=pct(lat, 95), found=found)


def stages():
    return sc._call(f"{sc.COLLECTOR}/local/stages")[1]


def collector_intake():
    before = stages()
    host = "h-" + uuid.uuid4().hex[:4]
    ts = sc.iso(time.time() - 120)
    lines = [f"ts={ts} host={host} metric=cpu_pct value=30" for _ in range(N_LINES)]
    t0 = time.perf_counter()
    for i in range(0, len(lines), CHUNK):
        sc.collector_send(lines[i:i + CHUNK])
    wall = time.perf_counter() - t0
    time.sleep(2)
    after = stages()
    return dict(lines=N_LINES, lps=N_LINES / wall, wall=wall,
                received=after["received"] - before["received"],
                aggregated=after["aggregated_into_windows"] - before["aggregated_into_windows"])


if __name__ == "__main__":
    a = saas_ingest()
    c = collector_intake()
    print("\nResult                         value")
    print("-" * 44)
    print(f"SaaS payloads sent/accepted    {a['sent']} / {a['accepted']}")
    print(f"SaaS failed requests           {a['failed']}")
    print(f"SaaS payloads/second           {a['pps']:.0f}  ({a['wall']:.1f}s)")
    print(f"SaaS request p50 / p95 (ms)    {a['p50']:.0f} / {a['p95']:.0f}  (batch of {BATCH})")
    print(f"SaaS spot check found          {a['found']} / 20")
    print(f"Collector lines/second         {c['lps']:.0f}  ({c['wall']:.1f}s)")
    print(f"Collector received / aggregated {c['received']} / {c['aggregated']} of {c['lines']}")
