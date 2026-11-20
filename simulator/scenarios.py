"""Live-scenario injector: each judge scenario from one command, with the expected result and a check.

    python simulator/scenarios.py --list
    python simulator/scenarios.py failed-logins
    python simulator/scenarios.py outage

Run a steady stream first (python simulator/generator.py --seconds 120) so the SaaS has a baseline
(it needs 8 windows of history per metric before it scores anomalies; hard limits still fire without one).

Demo tip: the SaaS correlates alerts by source within a 120 s window, so scenarios run back to back on the same
host join the same incident (that is the noise reduction working). Wait about 2 minutes between scenarios on one
host, or use different hosts, when you want each to show as its own incident.

Environment (defaults are the local dev setup):
    COLLECTOR_URL=http://127.0.0.1:8101   SAAS_URL=http://127.0.0.1:8000
    DASHBOARD_TOKEN=dash-acme             COLLECTOR_KEY=key-acme-1   COLLECTOR_SECRET=dev-secret-acme
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import signal
import ssl
import subprocess
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib import error, request

COLLECTOR = os.getenv("COLLECTOR_URL", "http://127.0.0.1:8101").rstrip("/")
SAAS = os.getenv("SAAS_URL", "http://127.0.0.1:8000").rstrip("/")
DASH = os.getenv("DASHBOARD_TOKEN", "dash-acme")
KEY = os.getenv("COLLECTOR_KEY", "key-acme-1")
SECRET = os.getenv("COLLECTOR_SECRET", "dev-secret-acme")
WINDOW = 5  # must match the collector's WINDOW_S


# ---------- plumbing ----------
SAAS_CA = os.getenv("SAAS_CA_FILE", "")  # set by demo.ps1 when the stack runs with -Tls


def _ctx(url):
    """HTTPS always verifies; with SAAS_CA_FILE set, only that CA is trusted."""
    if not url.startswith("https://"):
        return None
    return ssl.create_default_context(cafile=SAAS_CA or None)


def _call(url, data=None, headers=None, method=None):
    req = request.Request(url, data=data, headers=headers or {}, method=method or ("POST" if data is not None else "GET"))
    try:
        with request.urlopen(req, timeout=10, context=_ctx(url)) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else None)
    except error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def collector_send(lines):
    return _call(f"{COLLECTOR}/ingest", "\n".join(lines).encode())[1]


def saas_get(path):
    return _call(f"{SAAS}{path}", headers={"Authorization": f"Bearer {DASH}"})[1]


def saas_post_signed(payloads):
    body = json.dumps(payloads, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return _call(f"{SAAS}/v1/ingest", body, {"X-Collector-Key": KEY, "X-Signature": sig, "Content-Type": "application/json"})


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def windows(n=3):
    """Timestamps of n consecutive past windows, newest last, all safely before 'now'."""
    base = (int(time.time()) // WINDOW) * WINDOW - WINDOW * n
    return [base + i * WINDOW + 1 for i in range(n)]


def metric_lines(host, name, value, n=3, per_window=3):
    out = []
    for w in windows(n):
        for k in range(per_window):
            out.append(json.dumps({"kind": "metric", "ts": iso(w + k), "host": host, "name": name, "value": value}))
    return out


def failed_login_lines(host, count):
    t = iso(windows(1)[0])
    return [f'ts={t} host={host} msg="Failed password for root from 203.0.113.{i % 250 + 1} port 22"' for i in range(count)]


def expect(text):
    print(f"  EXPECT: {text}")


def wait_flush(seconds=WINDOW + 4):
    print(f"  waiting {seconds}s for windows to close and deliver...")
    time.sleep(seconds)


def show_incidents():
    inc = saas_get("/v1/incidents")
    if not isinstance(inc, list):
        print("  (could not read incidents:", inc, ")")
        return
    print(f"  SaaS shows {len(inc)} incident(s)")
    for i in inc[:3]:
        rec = i.get("recommendation", {})
        print(f"    - {i.get('severity')} | {rec.get('likely_cause')} | {i.get('alert_count')} alerts | {rec.get('action')}")


def reconcile(settle=30, cutoff_age=12):
    """Prove zero loss by comparing ID sets, not counts.

    A live stream keeps creating new payloads, so we only judge payloads at least `cutoff_age` seconds old:
    those must all be at the SaaS (we retry until they settle). Newer ones are still legitimately in flight.
    """
    cutoff = time.time() - cutoff_age
    deadline = time.time() + settle
    while True:
        eg = _call(f"{COLLECTOR}/local/egress?limit=20000")[1]
        proof = saas_get("/v1/proof")
        if not isinstance(eg, list) or not isinstance(proof, dict):
            print("  (reconcile skipped: could not read both sides)")
            return
        due = {e["payload_id"] for e in eg if e["created_at"] <= cutoff}
        got = set(proof.get("received_ids", []))
        missing = due - got
        if not missing or time.time() > deadline:
            break
        time.sleep(2)
    known = {e["payload_id"] for e in eg}
    in_flight = sum(1 for e in eg if e["status"] == "pending")
    print(f"  collector created {len(known)} payload(s); {len(due)} are old enough to judge")
    print(f"  of those, missing at the SaaS: {len(missing)} | still in flight (newer): {in_flight}")
    print(f"  SaaS duplicates stored: {proof.get('stored_duplicates')} | IDs at the SaaS the collector never made: {len(got - known)} (e.g. the 'delivery' scenario injects its own)")
    print("  RESULT: " + ("zero loss, zero duplicates (by ID set)" if not missing and not proof.get("stored_duplicates") else "LOSS OR DUPLICATES, investigate"))


# ---------- scenarios ----------
def secret():
    expect("the secret lines stay local; the SaaS only ever gets counts and a template summary")
    collector_send([
        "Nov 20 09:15:01 web-1 app[311]: user alice@corp.com logged in from 10.2.4.7 password=Hunter2! token=abc123def456",
        "Nov 20 09:15:02 web-1 app[311]: using key AKIAABCDEFGHIJKLMNOP and Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghijk",
    ])
    wait_flush()
    eg = json.dumps(_call(f"{COLLECTOR}/local/egress?limit=20")[1])
    for s in ["Hunter2", "alice@corp.com", "10.2.4.7", "AKIAABCDEFGHIJKLMNOP", "abc123def456", "web-1"]:
        print(f"  {s!r:26} leaked into egress? {s in eg}")
    print("  Open", f"{COLLECTOR}/local/raw", "(secrets visible, local) and", f"{COLLECTOR}/local/egress", "(what left)")


def failed_logins():
    expect("one auth_failure_burst event (count=30, critical) and no raw login records exported")
    collector_send(failed_login_lines("web-1", 30))
    wait_flush()
    eg = _call(f"{COLLECTOR}/local/egress?limit=200")[1]
    sent = [e["payload"]["event"] for e in eg if "event" in e["payload"] and e["payload"]["event"]["category"].startswith("auth_failure")]
    for ev in sent[:3]:
        print(f"  egress: {ev['category']} | {ev['severity']} | count={ev['count']} | '{ev['summary']}'")
    print(f"  (30 raw login lines became {len(sent)} event payload(s); the lines themselves never left)")
    show_incidents()


def cpu_spike():
    expect("CPU on web-1 flagged; the incident lists the CPU signal, its baseline and a recommendation")
    collector_send(metric_lines("web-1", "cpu_pct", 97))
    wait_flush()
    show_incidents()


def latency():
    expect("latency on router-1 rises: affected source, severity, trend and the related service impact")
    collector_send(metric_lines("router-1", "latency_ms", 600))
    wait_flush()
    show_incidents()


def packet_loss():
    expect("packet loss on router-1 above the 5% poor threshold, raised as an alert with its source")
    collector_send(metric_lines("router-1", "packet_loss_pct", 8))
    wait_flush()
    show_incidents()


def disk():
    expect("disk on db-1 above 95%: a critical capacity alert")
    collector_send(metric_lines("db-1", "disk_pct", 97))
    wait_flush()
    show_incidents()


def alert_storm():
    expect("many related alerts on one source collapse into ONE incident (noise reduction)")
    lines = (
        metric_lines("web-1", "cpu_pct", 97)
        + metric_lines("web-1", "latency_ms", 600)
        + metric_lines("web-1", "packet_loss_pct", 8)
        + failed_login_lines("web-1", 30)
    )
    collector_send(lines)
    wait_flush()
    show_incidents()


def outage():
    expect("collector keeps working while the SaaS link is down, buffers locally, then delivers everything on reconnect")
    _call(f"{COLLECTOR}/local/saas-link/down", b"")
    print("  link DOWN: sending data...")
    collector_send(metric_lines("web-2", "cpu_pct", 55, n=4))
    time.sleep(WINDOW + 4)
    buf = _call(f"{COLLECTOR}/local/buffer")[1]
    print(f"  buffered locally while down: {buf['pending']} payload(s), link={buf['link']}")
    _call(f"{COLLECTOR}/local/saas-link/up", b"")
    print("  link UP: waiting for replay...")
    time.sleep(8)
    reconcile()


def delivery():
    expect("duplicates are stored once; out-of-order events are placed by event time; a changed body under one ID is a conflict")
    now = time.time()

    def pl(offset, value, pid=None):
        return {
            "payload_id": pid or str(uuid.uuid4()),
            "tenant_ref": os.getenv("TENANT_REF", "t-acme"),
            "collector_id": os.getenv("COLLECTOR_ID", "col-blr-01"),
            "source_id": "src_deadbeef0001",
            "region": os.getenv("REGION", "in"),
            "event_ts_utc": iso(now - offset),
            "source_tz": "UTC",
            "window_s": 5,
            "metric": {"name": "bandwidth_mbps", "value": value, "unit": "mbps"},
            "health_state": "Good",
            "collector_version": "0.1.0",
        }

    newer, older = pl(10, 111.0), pl(60, 222.0)
    print("  send NEWER first:", saas_post_signed([newer])[1])
    print("  send OLDER second (arrives late):", saas_post_signed([older])[1])
    print("  resend NEWER (duplicate):", saas_post_signed([newer])[1])
    changed = {**newer, "metric": {**newer["metric"], "value": 999.0}}
    print("  same ID, different body (conflict):", saas_post_signed([changed])[1])
    pts = saas_get("/v1/metrics?name=bandwidth_mbps&source=src_deadbeef0001")
    if isinstance(pts, list):
        order = [(p["event_ts_utc"], p["metric"]["value"]) for p in pts if p["payload_id"] in (newer["payload_id"], older["payload_id"])]
        print("  stored order by event time:", order)
        print("  RESULT:", "ordered by event time, stored once" if [v for _, v in order] == [222.0, 111.0] else "CHECK ORDER")


def remediation():
    expect("an incident is proposed for remediation: approval step, audit record and rollback plan (simulation only)")
    inc = saas_get("/v1/incidents")
    if not isinstance(inc, list) or not inc:
        print("  no incident yet. Run 'alert-storm' or 'cpu-spike' first.")
        return
    ident = inc[0]["id"]
    status, res = _call(f"{SAAS}/v1/remediation/{ident}/approve", b"", {"Authorization": f"Bearer {DASH}"}, "POST")
    print(f"  approve incident {ident[:8]} -> HTTP {status}")
    print("  ", json.dumps(res, indent=2) if isinstance(res, dict) else res)


def _lb_status():
    status, body = _call(f"{SAAS}/_lb/status")
    return body if status == 200 and isinstance(body, dict) else None


def _print_lb(label):
    lb = _lb_status()
    if lb is None:
        print(f"  {label}: no failover proxy at {SAAS} (started with -NoProxy?)")
        return False
    ups = ", ".join(f"{u['url'].rsplit(':', 1)[1]}={'up' if u['healthy'] else 'DOWN'}({u['requests']} req)" for u in lb["upstreams"])
    print(f"  {label}: {ups} | failovers={lb['failovers']}")
    return True


def failover():
    expect("replica 1 is killed mid-stream; the proxy fails over to replica 2; the collector loses and duplicates nothing")
    pids_file = Path(__file__).resolve().parents[1] / "data" / "run.pids.json"
    try:
        procs = json.loads(pids_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        print("  cannot read data/run.pids.json: start the stack with .\\scripts\\run-local.ps1")
        return
    target = next((p for p in procs if p["name"] == "saas-1"), None)
    if target is None or not _print_lb("before"):
        print("  needs the stack from run-local.ps1 with the failover proxy (not -NoProxy)")
        return
    print(f"  killing saas-1 (pid {target['pid']}) while data is flowing ...")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(target["pid"]), "/T", "/F"], capture_output=True)
    else:
        os.kill(target["pid"], signal.SIGTERM)
    time.sleep(6)
    _print_lb("6 s after the kill")
    print("  healthz through the proxy:", _call(f"{SAAS}/healthz")[1])
    time.sleep(10)
    _print_lb("16 s after the kill")
    reconcile()
    print("  Restore replica 1 with: .\\scripts\\run-local.ps1 -Restart   (the database is kept)")


def tls():
    expect("plain HTTP is refused; HTTPS with our CA works; any other CA is rejected; a tampered body is a 401")
    if not SAAS.startswith("https://"):
        print("  The SaaS is not on https. Start the stack with:  .\\scripts\\run-local.ps1 -Tls")
        return
    plain = "http://" + SAAS[len("https://"):]
    try:
        request.urlopen(plain + "/healthz", timeout=5)
        print("  1. plain HTTP to the TLS port: ANSWERED  <- BAD")
    except Exception as e:  # the TLS server cannot speak HTTP: it resets or closes the connection
        print(f"  1. plain HTTP to the TLS port: REFUSED ({type(e).__name__})")

    status, body = _call(f"{SAAS}/healthz")
    print(f"  2. HTTPS with the dev CA: HTTP {status} {body}")

    try:
        request.urlopen(f"{SAAS}/healthz", timeout=5, context=ssl.create_default_context())  # system trust store only
        print("  3. HTTPS trusting only the system store: ACCEPTED  <- BAD")
    except Exception as e:
        reason = getattr(e, "reason", e)
        print(f"  3. HTTPS trusting a different CA (the system store): REJECTED ({type(reason).__name__}: certificate not trusted)")

    original = b'[{"payload_id":"x"}]'
    sig = hmac.new(SECRET.encode(), original, hashlib.sha256).hexdigest()
    status, _ = _call(f"{SAAS}/v1/ingest", original.replace(b'"x"', b'"y"'), {"X-Collector-Key": KEY, "X-Signature": sig, "Content-Type": "application/json"})
    print(f"  4. body changed after signing: HTTP {status}  " + ("(rejected as expected)" if status == 401 else "<- BAD, expected 401"))

    buf = _call(f"{COLLECTOR}/local/buffer")[1]
    if isinstance(buf, dict):
        print(f"  5. collector transport: {buf.get('transport')} | pending={buf.get('pending')} | last_error={buf.get('last_error')}")


SCENARIOS = {
    "failover": failover,
    "tls": tls,
    "secret": secret,
    "outage": outage,
    "failed-logins": failed_logins,
    "latency": latency,
    "cpu-spike": cpu_spike,
    "packet-loss": packet_loss,
    "disk": disk,
    "alert-storm": alert_storm,
    "delivery": delivery,
    "remediation": remediation,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", nargs="?", choices=sorted(SCENARIOS))
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list or not args.scenario:
        print("Scenarios:", ", ".join(sorted(SCENARIOS)))
        return
    print(f"== {args.scenario} ==")
    SCENARIOS[args.scenario]()


if __name__ == "__main__":
    main()
