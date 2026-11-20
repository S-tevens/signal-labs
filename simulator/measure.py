"""Measurement harness (E14): the three real-time targets and delivery, measured from timestamps.

    python simulator/measure.py all            # everything (about 5 minutes)
    python simulator/measure.py latency        # collection -> dashboard, target p95 <= 10 s
    python simulator/measure.py alert          # injected threshold breach (99% CPU) -> incident, target <= 15 s
    python simulator/measure.py anomaly        # deviation from baseline below any threshold (70% CPU) -> incident, target <= 15 s
    python simulator/measure.py offline        # collector killed -> state Poor, target <= 60 s
    python simulator/measure.py delivery       # forced outage -> sent IDs vs received IDs, zero loss and duplicates

Needs the stack from scripts/run-local.ps1 (use scripts/measure.ps1, which sets the environment).
Every test uses LIVE timestamps (never backdated) on a unique host, so it cannot disturb or be confused with the
other traffic, and every result is PASS or FAIL against its target with the raw timestamps saved as evidence.

How the dashboard is measured. The platform pushes a server-sent "snapshot" about every 2 s; the real dashboard reacts
by fetching the fleet, incidents, proof and four metric series, then renders. This harness does the same fetches when
a snapshot arrives and records when they complete ("dashboard path"). It also polls the API twice a second
("API"), the earliest moment the data could be shown (accurate to about half a second).

Two definitions of collection latency are reported because the collector sends one summary per 5 s window:
  from the newest record in the window   (the payload's own event timestamp)
  from the start of the window           (the earliest record it could contain: the strict, worst-case reading)
The verdict uses the strict one.

All timestamps are on one machine, so one clock. If the organizers measure across machines, agree a time source first.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenarios as sc  # noqa: E402  (environment, HTTP helpers and TLS handling shared with the scenarios)

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"dashboard_p95_s": 10.0, "alert_s": 15.0, "offline_s": 60.0}


# ---------------------------------------------------------------- pure helpers (unit tested)
def parse_ts(value: str) -> float:
    """ISO-8601 UTC string -> epoch seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def iso_ms(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile, the same rule the platform uses for its p95."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None}
    r = lambda x: round(x, 3)  # noqa: E731
    return {"n": len(values), "min": r(min(values)), "p50": r(percentile(values, 0.50)), "p95": r(percentile(values, 0.95)),
            "p99": r(percentile(values, 0.99)), "max": r(max(values))}


def window_start(event_ts: float, window_s: int) -> float:
    """Start of the aggregation window an event timestamp falls in."""
    return (int(event_ts) // max(1, int(window_s))) * max(1, int(window_s))


def attribute(egress: list[dict], raw: list[dict], label: str) -> dict[str, dict]:
    """Payloads built from raw records that mention `label` (our unique host). Returns payload_id -> payload.

    The collector pseudonymizes host names, so we cannot find our payloads by host. Instead we use the collector's own
    local lineage: egress rows know which raw record ids they summarize, and raw rows keep the original text.
    """
    raw_ids = {r["id"] for r in raw if label in r.get("text", "")}
    return {e["payload_id"]: e["payload"] for e in egress if raw_ids.intersection(e.get("raw_ids", []))}


def latency_summary(payloads: dict[str, dict], seen_api: dict, seen_dash: dict) -> dict:
    """Collection latency for our payloads, on both paths and both definitions. Pure function of the observations."""
    series: dict[str, list[float]] = {k: [] for k in ("dash_from_newest", "dash_from_window", "api_from_newest", "api_from_window")}
    never_dash = never_api = 0
    for pid, p in payloads.items():
        newest = parse_ts(p["event_ts_utc"])
        start = window_start(newest, p.get("window_s", 5))
        if pid in seen_api:
            series["api_from_newest"].append(seen_api[pid] - newest)
            series["api_from_window"].append(seen_api[pid] - start)
        else:
            never_api += 1
        if pid in seen_dash:
            series["dash_from_newest"].append(seen_dash[pid] - newest)
            series["dash_from_window"].append(seen_dash[pid] - start)
        else:
            never_dash += 1
    out = {name: stats(vals) for name, vals in series.items()}
    p95 = out["dash_from_window"]["p95"]
    out.update({"payloads": len(payloads), "never_seen_on_dashboard_path": never_dash, "never_seen_on_api": never_api})
    out["target_s"] = TARGETS["dashboard_p95_s"]
    out["verdict"] = "PASS" if (p95 is not None and p95 <= TARGETS["dashboard_p95_s"] and never_dash == 0) else "FAIL"
    return out


def alert_summary(t0: float, incident: dict | None, seen_api: float | None, seen_dash: float | None) -> dict:
    if incident is None:
        return {"verdict": "FAIL", "reason": "no alert appeared for the injected spike", "target_s": TARGETS["alert_s"]}
    created = incident.get("created_at_epoch")
    dash_s = None if seen_dash is None else round(seen_dash - t0, 3)
    first = (incident.get("signals") or [{}])[0]
    return {
        "from_spike_to_incident_created_s": None if created is None else round(created - t0, 3),
        "from_spike_to_api_visible_s": None if seen_api is None else round(seen_api - t0, 3),
        "from_spike_to_dashboard_path_s": dash_s,
        "alerts_grouped": incident.get("alert_count"),
        "first_signal": {k: first.get(k) for k in ("signal", "method", "value", "event_ts_utc", "alert_delay_s")},
        "target_s": TARGETS["alert_s"],
        "verdict": "PASS" if dash_s is not None and dash_s <= TARGETS["alert_s"] else "FAIL",
    }


def offline_summary(t_kill: float, last_seen: float | None, first_state_at: dict[str, float], dash_poor: float | None) -> dict:
    poor = first_state_at.get("Poor")
    s_kill = None if poor is None else round(poor - t_kill, 3)
    s_hb = None if poor is None or last_seen is None else round(poor - last_seen, 3)
    return {
        "from_outage_start_to_Poor_s": s_kill,
        "from_last_heartbeat_to_Poor_s": s_hb,
        "from_outage_start_to_Fair_s": None if "Fair" not in first_state_at else round(first_state_at["Fair"] - t_kill, 3),
        "from_outage_start_to_Poor_on_dashboard_path_s": None if dash_poor is None else round(dash_poor - t_kill, 3),
        "target_s": TARGETS["offline_s"],
        "verdict": "PASS" if s_hb is not None and s_hb <= TARGETS["offline_s"] else "FAIL",
    }


def delivery_summary(collector_ids: set[str], platform_ids: list[str], duplicate_attempts_delta: int, extra: dict) -> dict:
    platform_set = set(platform_ids)
    missing = sorted(collector_ids - platform_set)
    duplicate_rows = len(platform_ids) - len(platform_set)
    return {
        **extra,
        "payloads_created_in_window": len(collector_ids),
        "missing_at_platform": len(missing),
        "missing_examples": missing[:5],
        "duplicate_rows_at_platform": duplicate_rows,
        "duplicate_attempts_rejected_by_platform": duplicate_attempts_delta,
        "verdict": "PASS" if not missing and duplicate_rows == 0 else "FAIL",
    }


# ---------------------------------------------------------------- observation (what the dashboard would see)
class Observer:
    """Records the first moment each payload, incident and fleet state becomes visible, on two paths."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.payload_api: dict[str, float] = {}
        self.payload_dash: dict[str, float] = {}
        self.incident_api: dict[str, tuple[float, dict]] = {}
        self.incident_dash: dict[str, float] = {}
        self.state_api: dict[tuple[str, str], float] = {}  # (collector, state) -> first time seen
        self.state_dash: dict[tuple[str, str], float] = {}
        self.fleet_latest: dict[str, dict] = {}
        self.dash_fetch_s: list[float] = []
        self.snapshots = 0
        self.threads: list[threading.Thread] = []

    def _record(self, metrics, incidents, fleet, t, api: bool):
        with self.lock:
            target_p = self.payload_api if api else self.payload_dash
            for m in metrics or []:
                target_p.setdefault(m["payload_id"], t)
            for i in incidents or []:
                if api:
                    self.incident_api.setdefault(i["id"], (t, i))
                    self.incident_api[i["id"]] = (self.incident_api[i["id"]][0], i)
                else:
                    self.incident_dash.setdefault(i["id"], t)
            target_s = self.state_api if api else self.state_dash
            for f in fleet or []:
                target_s.setdefault((f["collector_id"], f["state"]), t)
                if api:
                    self.fleet_latest[f["collector_id"]] = f

    def _api_loop(self):
        while not self.stop_event.is_set():
            try:
                since = iso_ms(time.time() - 180)
                metrics = sc.saas_get(f"/v1/metrics?from={since}&limit=10000")
                incidents = sc.saas_get("/v1/incidents")
                fleet = sc.saas_get("/v1/fleet")
                t = time.time()
                if isinstance(metrics, list) and isinstance(incidents, list) and isinstance(fleet, list):
                    self._record(metrics, incidents, fleet, t, api=True)
            except (error.URLError, OSError, ValueError):
                pass
            self.stop_event.wait(0.5)

    def _dashboard_fetch(self):
        """The fetches the real dashboard makes when a snapshot arrives (see dashboard/src/api.js)."""
        started = time.time()
        since = iso_ms(time.time() - 30 * 60)
        paths = ["/v1/fleet", "/v1/incidents", "/v1/proof?window_s=300"] + [
            f"/v1/metrics?name={n}&from={since}&limit=10000" for n in ("cpu_pct", "mem_pct", "latency_ms", "packet_loss_pct")
        ]
        try:
            with ThreadPoolExecutor(max_workers=len(paths)) as pool:
                results = list(pool.map(sc.saas_get, paths))
        except (error.URLError, OSError, ValueError):
            return
        done = time.time()  # the page renders right after these complete
        fleet, incidents = results[0], results[1]
        metrics = [m for r in results[3:] if isinstance(r, list) for m in r]
        if isinstance(fleet, list) and isinstance(incidents, list):
            self._record(metrics, incidents, fleet, done, api=False)
            with self.lock:
                self.dash_fetch_s.append(done - started)

    def _sse_loop(self):
        while not self.stop_event.is_set():
            try:
                req = request.Request(f"{sc.SAAS}/v1/stream", headers={"Authorization": f"Bearer {sc.DASH}"})
                with request.urlopen(req, timeout=8, context=sc._ctx(sc.SAAS)) as resp:
                    saw_event = False
                    for raw in resp:
                        if self.stop_event.is_set():
                            return
                        line = raw.decode("utf-8", "replace").strip()
                        if line.startswith("event: snapshot"):
                            saw_event = True
                        elif line == "" and saw_event:  # the blank line ends one event: the dashboard refreshes now
                            saw_event = False
                            with self.lock:
                                self.snapshots += 1
                            self._dashboard_fetch()
            except (error.URLError, OSError, ValueError):
                self.stop_event.wait(1.0)

    def start(self):
        for target in (self._api_loop, self._sse_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.stop_event.set()

    def wait_for(self, predicate, timeout: float, step: float = 0.25):
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                if predicate():
                    return True
            time.sleep(step)
        return False


# ---------------------------------------------------------------- traffic
def inject_second(host: str, cpu: float, extra: bool = True) -> float:
    """Send one second's worth of records for `host`, with live timestamps. Returns the event timestamp used."""
    t = time.time()
    ts = iso_ms(t)
    rows = [{"kind": "metric", "ts": ts, "host": host, "name": "cpu_pct", "value": round(cpu, 1)}]
    if extra:
        rows += [{"kind": "metric", "ts": ts, "host": host, "name": "mem_pct", "value": round(random.gauss(55, 1), 1)},
                 {"kind": "metric", "ts": ts, "host": host, "name": "latency_ms", "value": round(abs(random.gauss(40, 2)), 1)}]
    sc.collector_send([json.dumps(r) for r in rows])
    return t


def run_stream(host: str, seconds: float, cpu_fn) -> list[float]:
    """One record set per second for `seconds`, on a steady clock. Returns the event timestamps sent."""
    sent, start = [], time.time()
    n = 0
    while time.time() - start < seconds:
        sent.append(inject_second(host, cpu_fn(n)))
        n += 1
        time.sleep(max(0.0, start + n * 1.0 - time.time()))
    return sent


def local_attribution(label: str) -> dict[str, dict]:
    egress = sc._call(f"{sc.COLLECTOR}/local/egress?limit=5000")[1]
    raw = sc._call(f"{sc.COLLECTOR}/local/raw?limit=5000")[1]
    if not isinstance(egress, list) or not isinstance(raw, list):
        raise SystemExit("cannot read the collector's local views; is the collector running on this machine?")
    return attribute(egress, raw, label)


# ---------------------------------------------------------------- the four tests
def test_latency(obs: Observer, duration: float) -> dict:
    label = "measure-lat-" + uuid.uuid4().hex[:4]
    print(f"  streaming live records for host {label} for {duration:.0f} s ...")
    run_stream(label, duration, lambda n: random.gauss(35, 2))
    print("  draining (waiting for the last windows to close and reach the dashboard path) ...")
    time.sleep(14)
    payloads = local_attribution(label)
    with obs.lock:
        api, dash = dict(obs.payload_api), dict(obs.payload_dash)
    res = latency_summary(payloads, api, dash)
    res["host"] = label
    res["samples"] = [{"payload_id": pid, "event_ts_utc": p["event_ts_utc"], "window_s": p.get("window_s"), "seen_api": api.get(pid), "seen_dashboard_path": dash.get(pid)}
                      for pid, p in list(payloads.items())[:400]]
    with obs.lock:
        res["dashboard_snapshots_seen"] = obs.snapshots
        res["dashboard_fetch_s"] = stats(list(obs.dash_fetch_s))
    return res


def test_alert(obs: Observer, warmup: float, spike_max: float, value: float = 99.0, prefix: str = "measure-alert-") -> dict:
    """`value` 99 crosses a hard threshold; 70 stays below every threshold and is caught only as a deviation from baseline."""
    label = prefix + uuid.uuid4().hex[:4]
    print(f"  warming up a baseline for {label} ({warmup:.0f} s of normal CPU) ...")
    run_stream(label, warmup, lambda n: random.gauss(35, 2))
    time.sleep(8)
    payloads = local_attribution(label)
    if not payloads:
        return {"verdict": "FAIL", "reason": "no payloads were produced for the test host"}
    source = next(iter(payloads.values()))["source_id"]
    with obs.lock:
        known = set(obs.incident_api)
    print(f"  injecting a CPU spike ({value:g}%) on source {source} with live timestamps ...")
    t0 = time.time()
    found = None
    for n in range(int(spike_max)):
        inject_second(label, value - random.random() * 0.4)
        with obs.lock:
            found = next(((i, t) for iid, (t, i) in obs.incident_api.items() if iid not in known and i.get("source_id") == source), None)
        if found:
            break
        time.sleep(max(0.0, t0 + (n + 1) - time.time()))
    incident, seen_api = (found[0], found[1]) if found else (None, None)
    seen_dash = None
    if incident:
        iid = incident["id"]
        obs.wait_for(lambda: iid in obs.incident_dash, timeout=10)
        with obs.lock:
            seen_dash = obs.incident_dash.get(iid)
    res = alert_summary(t0, incident, seen_api, seen_dash)
    res.update({"host": label, "source_id": source, "spike_started_epoch": t0, "spike_value_pct": value})
    return res


def spawn_enrolled_collector(port: int, workdir: Path, label: str):
    """A separate collector that enrolls itself, with host telemetry off, so only its heartbeat keeps it alive."""
    admin = os.getenv("DASHBOARD_ADMIN_TOKEN", "dash-admin")
    cid = f"col-{label}"
    status, res = sc._call(f"{sc.SAAS}/v1/enrollment-tokens", json.dumps({"collector_id": cid, "expires_in_s": 300}).encode(),
                           {"Authorization": f"Bearer {admin}", "Content-Type": "application/json"}, "POST")
    if status != 200 or not isinstance(res, dict):
        raise SystemExit(f"could not issue an enrollment token (HTTP {status}); is the stack running with the admin token?")
    env = {**os.environ, "DATA_DIR": str(workdir), "ENROLL_TOKEN": res["token"], "ENROLL_TENANT": res["tenant_ref"], "SAAS_URL": sc.SAAS,
           "HOST_TELEMETRY": "0", "HEARTBEAT_INTERVAL_S": "5", "REQUIRE_TLS": "1" if sc.SAAS.startswith("https://") else "0"}
    for name in ("COLLECTOR_KEY", "COLLECTOR_SECRET", "PSEUDO_SECRET", "COLLECTOR_ID", "TENANT_REF", "REGION"):
        env.pop(name, None)
    if sc.SAAS_CA:
        env["SAAS_CA_FILE"] = sc.SAAS_CA
    if not sc.SAAS.startswith("https://"):
        env["ENROLL_ALLOW_HTTP"] = "1"
    log = open(ROOT / "data" / "logs" / f"{label}.log", "wb")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "collector.main:app", "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
    return proc, cid, log


def test_offline(obs: Observer) -> dict:
    import shutil

    label = "measure-off-" + uuid.uuid4().hex[:4]
    workdir = ROOT / "data" / label
    (ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
    proc, cid, log = spawn_enrolled_collector(8104, workdir, label)
    try:
        print(f"  started collector {cid} (heartbeat every 5 s); waiting for it to appear healthy ...")
        ok = obs.wait_for(lambda: obs.fleet_latest.get(cid, {}).get("state") in ("Good", "Excellent") and obs.fleet_latest.get(cid, {}).get("online"), timeout=60)
        if not ok:
            return {"verdict": "FAIL", "reason": "the test collector never appeared healthy", "target_s": TARGETS["offline_s"]}
        time.sleep(8)  # a few heartbeats, so last_seen is meaningful
        with obs.lock:
            last_seen = obs.fleet_latest[cid].get("last_seen")
        print(f"  killing {cid} (hard kill, no goodbye) and waiting for the platform to mark it Poor ...")
        t_kill = time.time()
        proc.kill()
        # Only a "Poor" seen AFTER the kill counts, never one from before.
        obs.wait_for(lambda: obs.state_api.get((cid, "Poor"), 0) >= t_kill, timeout=100)
        obs.wait_for(lambda: obs.state_dash.get((cid, "Poor"), 0) >= t_kill, timeout=10)
        with obs.lock:
            seen = {state: t for (c, state), t in obs.state_api.items() if c == cid and t >= t_kill}
            dash_poor = obs.state_dash.get((cid, "Poor"))
            last_seen = max(last_seen or 0, (obs.fleet_latest.get(cid) or {}).get("last_seen") or 0) or last_seen
        res = offline_summary(t_kill, last_seen, seen, dash_poor if dash_poor and dash_poor >= t_kill else None)
        res.update({"collector": cid, "last_heartbeat_epoch": last_seen, "outage_started_epoch": t_kill})
        return res
    finally:
        if proc.poll() is None:
            proc.kill()
        log.close()
        shutil.rmtree(workdir, ignore_errors=True)


def test_delivery(obs: Observer, outage_s: float) -> dict:
    label = "measure-del-" + uuid.uuid4().hex[:4]
    proof0 = sc.saas_get("/v1/proof")
    dup0 = proof0.get("duplicate_attempts", 0) if isinstance(proof0, dict) else 0
    print(f"  steady traffic for 10 s, then the platform link goes DOWN for {outage_s:.0f} s ...")
    t_start = time.time()
    run_stream(label, 10, lambda n: random.gauss(35, 2))
    sc._call(f"{sc.COLLECTOR}/local/saas-link/down", b"")
    t_down = time.time()
    run_stream(label, outage_s, lambda n: random.gauss(35, 2))
    buffered = sc._call(f"{sc.COLLECTOR}/local/buffer")[1]
    pending_at_end = buffered.get("pending") if isinstance(buffered, dict) else None
    sc._call(f"{sc.COLLECTOR}/local/saas-link/up", b"")
    t_up = time.time()
    print(f"  link UP again with {pending_at_end} payload(s) buffered; waiting for the replay ...")
    run_stream(label, 5, lambda n: random.gauss(35, 2))
    window_end = time.time()

    def created_in_window():
        # Newest first, so a few thousand rows comfortably cover this test window without moving megabytes.
        eg = sc._call(f"{sc.COLLECTOR}/local/egress?limit=2500")[1]
        return [e for e in eg if t_start <= e["created_at"] <= window_end] if isinstance(eg, list) else []

    all_sent_at = None
    end = time.time() + 90
    while time.time() < end:
        rows = created_in_window()
        if rows and all(e["status"] == "sent" for e in rows):
            all_sent_at = time.time()
            break
        time.sleep(1.0)
    rows = created_in_window()
    proof = sc.saas_get("/v1/proof")
    platform_ids = proof.get("received_ids", []) if isinstance(proof, dict) else []
    dup1 = proof.get("duplicate_attempts", 0) if isinstance(proof, dict) else 0
    extra = {
        "host": label,
        "outage_duration_s": round(t_up - t_down, 1),
        "buffered_when_link_came_back": pending_at_end,
        "replay_seconds_after_reconnect": None if all_sent_at is None else round(all_sent_at - t_up, 2),
        "all_payloads_in_window_marked_sent": all_sent_at is not None,
    }
    res = delivery_summary({e["payload_id"] for e in rows}, platform_ids, dup1 - dup0, extra)
    if all_sent_at is None:
        res["verdict"] = "FAIL"
    return res


# ---------------------------------------------------------------- settings snapshot, report, CLI
def snapshot_settings() -> dict:
    timing = sc._call(f"{sc.COLLECTOR}/local/timing")[1]
    thresholds = {}
    path = ROOT / "saas" / "config" / "thresholds.yaml"
    if path.exists():
        for key in ("stale_after_s", "offline_after_s", "anomaly_persistence_windows", "baseline_min", "correlation_window_s"):
            m = re.search(rf"^{key}:\s*([0-9.]+)", path.read_text(encoding="utf-8"), re.M)
            if m:
                thresholds[key] = float(m.group(1))
    lb = sc._call(f"{sc.SAAS}/_lb/status")[1]
    return {"collector_timing": timing if isinstance(timing, dict) else None, "platform_thresholds_from_repo_file": thresholds,
            "failover_proxy": bool(isinstance(lb, dict) and lb.get("upstreams")), "saas_url": sc.SAAS}


def fmt(v, unit=" s"):
    return "n/a" if v is None else f"{v}{unit}"


def render_markdown(report: dict) -> str:
    r = report["results"]
    lines = [f"# Measurement run {report['started_utc']}", "",
             "Measured on one machine from live timestamps. Settings used are listed at the bottom. See `simulator/measure.py` for the method.", "",
             "| Target | Measured | Target | Verdict |", "|---|---|---|---|"]
    if "latency" in r:
        l = r["latency"]
        lines.append(f"| Collection to dashboard, p95 (strict: from window start) | {fmt(l['dash_from_window']['p95'])} (n={l['dash_from_window']['n']}) | ≤ {TARGETS['dashboard_p95_s']:g} s | **{l['verdict']}** |")
        lines.append(f"| Collection to dashboard, p95 (from newest record) | {fmt(l['dash_from_newest']['p95'])} | for reference | |")
        lines.append(f"| Collection to API, p95 (earliest possible, from window start) | {fmt(l['api_from_window']['p95'])} | for reference | |")
    if "alert" in r:
        a = r["alert"]
        lines.append(f"| Spike to alert on the dashboard path | {fmt(a.get('from_spike_to_dashboard_path_s'))} (incident created at {fmt(a.get('from_spike_to_incident_created_s'))}) | ≤ {TARGETS['alert_s']:g} s | **{a['verdict']}** |")
    if "anomaly" in r:
        a = r["anomaly"]
        lines.append(f"| Deviation from baseline (70% CPU, below every threshold) to alert | {fmt(a.get('from_spike_to_dashboard_path_s'))} (incident created at {fmt(a.get('from_spike_to_incident_created_s'))}) | ≤ {TARGETS['alert_s']:g} s | **{a['verdict']}** |")
    if "offline" in r:
        o = r["offline"]
        lines.append(f"| Collector offline to Poor, from last heartbeat | {fmt(o.get('from_last_heartbeat_to_Poor_s'))} (from outage start {fmt(o.get('from_outage_start_to_Poor_s'))}) | ≤ {TARGETS['offline_s']:g} s | **{o['verdict']}** |")
    if "delivery" in r:
        d = r["delivery"]
        lines.append(f"| Zero loss and zero duplicates through an outage | {d['payloads_created_in_window']} created, {d['missing_at_platform']} missing, {d['duplicate_rows_at_platform']} duplicate rows; replay took {fmt(d.get('replay_seconds_after_reconnect'))} | none missing, none duplicated | **{d['verdict']}** |")
    lines += ["", "## Settings used", "", "```json", json.dumps(report["settings"], indent=2), "```", "",
              "## Details", "", "Full raw timestamps are in the matching `.json` file next to this one."]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("which", nargs="*", default=None, metavar="{all,latency,alert,anomaly,offline,delivery}",
                    help="one or more tests (default: all)")
    ap.add_argument("--duration", type=float, default=60, help="seconds of live traffic for the latency test")
    ap.add_argument("--warmup", type=float, default=50, help="seconds of normal data before the spike (the platform needs about 40 s for a baseline)")
    ap.add_argument("--outage", type=float, default=15, help="seconds the platform link is cut in the delivery test")
    ap.add_argument("--out", default=str(ROOT / "docs" / "p3" / "evidence"), help="where to write the evidence files")
    args = ap.parse_args()

    if sc._call(f"{sc.COLLECTOR}/healthz")[0] != 200 or not isinstance(sc.saas_get("/v1/fleet"), list):
        print("The stack is not reachable. Start it with .\\scripts\\run-local.ps1 -Tls (and use scripts\\measure.ps1).")
        return 2

    started = datetime.now(timezone.utc)
    report = {"started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "settings": snapshot_settings(), "results": {}, "targets": TARGETS}
    obs = Observer()
    obs.start()
    time.sleep(3)  # let the observer see the starting state before any traffic
    tests = {"latency": lambda: test_latency(obs, args.duration), "alert": lambda: test_alert(obs, args.warmup, 45),
             "anomaly": lambda: test_alert(obs, args.warmup, 45, value=70.0, prefix="measure-anom-"),
             "offline": lambda: test_offline(obs), "delivery": lambda: test_delivery(obs, args.outage)}
    try:
        bad = [w for w in (args.which or []) if w not in ("all", *tests)]
        if bad:
            ap.error(f"unknown test(s) {bad}; choose from all, {', '.join(tests)}")
        chosen = list(tests) if not args.which or "all" in args.which else [n for n in tests if n in args.which]
        for name in chosen:
            print(f"== {name} ==")
            report["results"][name] = tests[name]()
            print(f"  -> {report['results'][name].get('verdict')}")
    finally:
        obs.stop()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    (out / f"measure-{stamp}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md = render_markdown(report)
    (out / f"measure-{stamp}.md").write_text(md, encoding="utf-8")
    print("\n" + md.split("## Settings used")[0])
    print(f"evidence written to {out / ('measure-' + stamp + '.md')} and .json")
    return 0 if all(v.get("verdict") == "PASS" for v in report["results"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
