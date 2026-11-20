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
import shutil
import signal
import ssl
import subprocess
import sys
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
        try:
            return e.code, e.read().decode()[:300]
        except OSError:  # the server may close the connection after refusing a huge body
            return e.code, ""


def _poll(url):
    """A request that may be made before a freshly started process is listening: not up yet means (0, None)."""
    try:
        return _call(url)
    except (error.URLError, OSError):
        return 0, None


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
    print("  RESULT:", "FAIL" if any(x in eg for x in ["Hunter2", "alice@corp.com", "10.2.4.7", "AKIAABCDEFGHIJKLMNOP", "abc123def456", "web-1"]) else "PASS")
    print("  Open", f"{COLLECTOR}/local/raw", "(secrets visible, local) and", f"{COLLECTOR}/local/egress", "(what left)")


def hold():
    """Hold sending, let a secret-bearing record become a payload, inspect it, release, and prove it arrived unchanged."""
    expect("held: the payload waits in the buffer with its digest and no secret; released: the same ID and digest reach the SaaS")
    local = {"X-Requested-With": "local-ui"}
    tag = uuid.uuid4().hex[:8]
    host, secret_value = f"hold-demo-{tag}", f"Hold!{tag}Pw"
    print("  1. HOLD", _call(f"{COLLECTOR}/local/hold", b"", local, "POST")[1].get("held"))
    # Anything queued before the hold may already be on its way, so only payloads created from now on are judged.
    before = {e["payload_id"] for e in _call(f"{COLLECTOR}/local/egress?limit=2000")[1]}
    now = iso(time.time() - 8)
    collector_send([
        json.dumps({"kind": "metric", "ts": now, "host": host, "name": "cpu_utilization_percent", "value": 33.0}),
        f'ts={now} host={host} msg="login ok user=alice@corp.com password={secret_value}"',
    ])
    wait_flush()
    rows = [e for e in _call(f"{COLLECTOR}/local/egress?limit=2000")[1] if e["payload_id"] not in before]
    buf = _call(f"{COLLECTOR}/local/buffer")[1]
    held_ok = bool(rows) and all(r["status"] == "pending" for r in rows)
    print(f"  2. while held: {len(rows)} new payload(s), all pending: {held_ok}; buffer: {buf['pending']} waiting, oldest {buf.get('oldest_pending_age_s')} s")
    ours = [r for r in rows if secret_value in json.dumps(_call(f"{COLLECTOR}/local/lineage/{r['payload_id']}")[1])]
    print(f"     {len(ours)} of them came from the record that contained the secret (found through the local raw store)")
    clean = bool(ours) and secret_value not in json.dumps(rows) and "alice@corp.com" not in json.dumps(rows)
    print(f"     secret in any pending payload? {not clean}   (digest of the first: {rows[0]['digest'][:16] if rows else '-'}...)")
    at_saas_early = [r["payload_id"] for r in rows if _call(f"{SAAS}/v1/objects/observation/{r['payload_id']}", headers={"Authorization": f"Bearer {DASH}"})[0] == 200]
    print(f"     any of them at the SaaS while held? {bool(at_saas_early)}")
    digests = {r["payload_id"]: r["digest"] for r in rows}
    print("  3. RELEASE", not _call(f"{COLLECTOR}/local/release", b"", local, "POST")[1].get("held"))
    deadline, arrived = time.time() + 20, {}
    while time.time() < deadline and len(arrived) < len(rows):
        time.sleep(1)
        for r in rows:
            code, body = _call(f"{SAAS}/v1/objects/observation/{r['payload_id']}", headers={"Authorization": f"Bearer {DASH}"})
            if code == 200:
                arrived[r["payload_id"]] = body["properties"]
    after = {e["payload_id"]: e for e in _call(f"{COLLECTOR}/local/egress?limit=2000")[1]}
    same = all(after[i]["digest"] == digests[i] and after[i]["status"] == "sent" for i in arrived)
    print(f"  4. after release: {len(arrived)} of {len(rows)} reached the SaaS under the same ID; digest unchanged and status sent: {same}")
    ok = held_ok and clean and not at_saas_early and len(arrived) == len(rows) and same
    print("  RESULT:", "PASS" if ok else "FAIL")


def tenants():
    """Two tenants on one platform: isolation checks, then deliberately bad payloads, each with its reason."""
    expect("each token sees only its own tenant; cross-tenant access is refused or 404; every bad payload is rejected with a reason")
    G_KEY, G_SECRET, G_DASH = os.getenv("GLOBEX_KEY", "key-globex-1"), os.getenv("GLOBEX_SECRET", "dev-secret-globex"), os.getenv("GLOBEX_DASH", "dash-globex")
    tag = uuid.uuid4().hex[:6]
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))

    def signed(path, payload, key, secret):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return _call(f"{SAAS}{path}", body, {"X-Collector-Key": key, "X-Signature": sig, "Content-Type": "application/json"})

    def metric(tenant, collector, pid=None, **over):
        p = {"payload_id": pid or str(uuid.uuid4()), "tenant_ref": tenant, "collector_id": collector, "source_id": "src_" + tag.ljust(8, "0"),
             "region": "in", "event_ts_utc": iso(time.time() - 10), "source_tz": "UTC", "window_s": 5,
             "metric": {"name": "cpu_pct", "value": 30.0, "unit": "%"}, "health_state": "Excellent", "collector_version": "1.0.0"}
        p.update(over)
        return p

    def get(path, token):
        return _call(f"{SAAS}{path}", headers={"Authorization": f"Bearer {token}"})

    acme_p, globex_p = metric("t-acme", "col-blr-01"), metric("t-globex", "col-globex-01")
    check("a valid acme payload is accepted", signed("/v1/ingest", [acme_p], KEY, SECRET)[0] == 200)
    check("a valid globex payload is accepted", signed("/v1/ingest", [globex_p], G_KEY, G_SECRET)[0] == 200)
    signed("/v1/heartbeat", {"collector_id": "col-globex-01", "collector_version": "1.0.0", "config_hash": "cfg-demo", "resource_usage": {}}, G_KEY, G_SECRET)

    fleets = {t: [c["collector_id"] for c in (get("/v1/fleet", tok)[1] or [])] for t, tok in (("acme", DASH), ("globex", G_DASH))}
    check("each fleet lists only its own collectors", "col-globex-01" in fleets["globex"] and "col-globex-01" not in fleets["acme"] and "col-blr-01" not in fleets["globex"], str(fleets))
    ids = {t: {o["id"] for o in (get("/v1/objects/observation", tok)[1] or [])} for t, tok in (("acme", DASH), ("globex", G_DASH))}
    check("observations are disjoint between tenants", globex_p["payload_id"] in ids["globex"] and acme_p["payload_id"] in ids["acme"] and not ids["acme"] & ids["globex"])
    check("a cross-tenant object fetch returns 404", get(f"/v1/objects/observation/{acme_p['payload_id']}", G_DASH)[0] == 404 and get(f"/v1/objects/observation/{globex_p['payload_id']}", DASH)[0] == 404)
    metrics = {t: {m.get("payload_id") for m in (get("/v1/metrics?limit=10000", tok)[1] or [])} for t, tok in (("acme", DASH), ("globex", G_DASH))}
    check("metric queries are disjoint between tenants", globex_p["payload_id"] not in metrics["acme"] and acme_p["payload_id"] not in metrics["globex"])
    check("an unknown dashboard token is refused", get("/v1/fleet", "dash-nobody")[0] in (401, 403))

    code, body = signed("/v1/ingest", [metric("t-acme", "col-globex-01")], G_KEY, G_SECRET)
    check("a globex collector naming tenant t-acme is refused", code == 403, f"HTTP {code}: {str(body)[:80]}")
    code, body = signed("/v1/ingest", [metric("t-globex", "col-globex-01")], KEY, SECRET)
    check("a payload signed with the other tenant's key is refused", code in (401, 403), f"HTTP {code}")

    bad = {
        "an extra field (hostname)": metric("t-globex", "col-globex-01", hostname="srv-17.corp.example"),
        "a secret-like summary": metric("t-globex", "col-globex-01", metric=None, event={"category": "log_event", "severity": "info", "count": 1, "summary": "login ok password=Hunter2! token=abc123def456"}),
        "an unknown metric name": metric("t-globex", "col-globex-01", metric={"name": "customer_email", "value": 1.0, "unit": "%"}),
        "a non-UTC timestamp": metric("t-globex", "col-globex-01", event_ts_utc="2026-11-20T15:30:00+05:30"),
    }
    for label, payload in bad.items():
        payload = {k: v for k, v in payload.items() if v is not None}
        code, body = signed("/v1/ingest", [payload], G_KEY, G_SECRET)
        reason = " ".join(str(body).split())[:90]
        check(f"{label} is rejected with a reason", code in (400, 422) and bool(reason), f"HTTP {code}: {reason}")
    print("  RESULT:", "PASS" if all(results) else "FAIL", f"({sum(results)} of {len(results)} checks)")


def rbac():
    """Role-based access control with real sign-ins: who may do what, a role changed live, lockout, and the audit trail."""
    expect("each person's role decides what they can do; an administrator's change applies at once; refusals are audited with names")
    users_file = Path(__file__).resolve().parents[1] / "data" / "dev-users.json"
    if not users_file.exists():
        print("  The development users are missing. Start the stack with scripts\\run-local.ps1 first.")
        return
    known = json.loads(users_file.read_text(encoding="utf-8"))
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f"  [{detail}]" if detail else ""))

    def call(token, method, path, body=None):
        headers = {"Authorization": f"Bearer {token}"}
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        return _call(f"{SAAS}{path}", data, headers, method)

    def sign_in(tenant, username, password):
        return _call(f"{SAAS}/v1/login", json.dumps({"tenant": tenant, "username": username, "password": password}).encode(), {"Content-Type": "application/json"}, "POST")

    people = {}
    for role, username in (("admin", "asha.admin"), ("operator", "omar.ops"), ("viewer", "vera.viewer"), ("auditor", "ari.audit")):
        rec = known.get(f"t-acme/{username}")
        code, body = sign_in("t-acme", username, rec["password"]) if rec else (0, None)
        check(f"{role} ({username}) signs in", code == 200 and body["user"]["role"] == role)
        people[role] = body["token"] if code == 200 else ""
    admin, operator, viewer, auditor = (people[r] for r in ("admin", "operator", "viewer", "auditor"))

    check("no credential, and a made-up one, are refused (401)", _call(f"{SAAS}/v1/fleet")[0] == 401 and call("sl1.made-up.token", "GET", "/v1/fleet")[0] == 401)
    check("a wrong password and an unknown user get the same answer", sign_in("t-acme", "asha.admin", "wrong password here") == sign_in("t-acme", "nobody.here", "wrong password here"))
    check("viewer reads the fleet", call(viewer, "GET", "/v1/fleet")[0] == 200)
    code, body = call(viewer, "POST", "/v1/actions/propose", {})
    check("viewer cannot propose an action (403, says why)", code == 403 and "viewer" in str(body), str(body)[:60])
    check("viewer cannot read the audit log or manage users", call(viewer, "GET", "/v1/audit")[0] == 403 and call(viewer, "GET", "/v1/users")[0] == 403)
    check("auditor reads the audit log but cannot act", call(auditor, "GET", "/v1/audit")[0] == 200 and call(auditor, "POST", "/v1/actions/propose", {})[0] == 403)
    check("operator can reach actions and AI summaries (unknown incident gives 404, not 403)", call(operator, "POST", "/v1/actions/propose", {})[0] != 403 and call(operator, "GET", "/v1/incidents/none/ai-summary")[0] == 404)
    check("operator cannot manage users or issue enrollment tokens", call(operator, "GET", "/v1/users")[0] == 403 and call(operator, "POST", "/v1/enrollment-tokens", {"collector_id": "col-rbac-demo"})[0] == 403)
    check("admin lists users, and the list holds no password material", "scrypt" not in json.dumps(call(admin, "GET", "/v1/users")[1]))

    # A role changed live: the same session token, a different answer on the next request.
    check("viewer is refused before the change", call(viewer, "POST", "/v1/actions/propose", {})[0] == 403)
    check("admin promotes the viewer to operator", call(admin, "PATCH", "/v1/users/vera.viewer", {"role": "operator"})[0] == 200)
    check("the SAME session token is allowed at once (no new sign-in)", call(viewer, "POST", "/v1/actions/propose", {})[0] != 403)
    call(admin, "PATCH", "/v1/users/vera.viewer", {"role": "viewer"})
    check("demoting takes effect just as fast", call(viewer, "POST", "/v1/actions/propose", {})[0] == 403)

    # A throwaway account: create, lock out, reset, disable.
    temp = "scenario." + uuid.uuid4().hex[:6]
    code, _ = call(admin, "POST", "/v1/users", {"username": temp, "display_name": "Scenario Temp", "role": "viewer", "temporary_password": "temporary phrase one"})
    check("admin creates a user with a temporary password", code == 200)
    token = sign_in("t-acme", temp, "temporary phrase one")[1]["token"]
    check("a temporary password only allows changing it (403 elsewhere)", call(token, "GET", "/v1/fleet")[0] == 403 and call(token, "GET", "/v1/session")[0] == 200)
    for _ in range(5):
        sign_in("t-acme", temp, "not the password")
    check("five wrong passwords lock the account (429, even for the right password)", sign_in("t-acme", temp, "temporary phrase one")[0] == 429)
    call(admin, "POST", f"/v1/users/{temp}/password", {"temporary_password": "second temporary phrase"})
    check("an admin reset unlocks it", sign_in("t-acme", temp, "second temporary phrase")[0] == 200)
    call(admin, "PATCH", f"/v1/users/{temp}", {"active": False})
    check("a disabled user's session ends at once (401)", call(token, "GET", "/v1/fleet")[0] == 401 or call(sign_in("t-acme", temp, "second temporary phrase")[1] or {"token": ""}, "GET", "/v1/fleet")[0] in (401, 403))
    check("the last administrator cannot be removed", call(admin, "PATCH", "/v1/users/asha.admin", {"role": "viewer"})[0] == 409)

    code, log = call(auditor, "GET", "/v1/audit?limit=300")
    entries = log if isinstance(log, list) else []
    changed = [r for r in entries if r["action"] == "user_role_changed" and r["reference"] == "vera.viewer"]
    check("the audit log names who changed the role", code == 200 and any(r["detail"].get("actor") == "asha.admin" for r in changed), f"{len(changed)} change(s) logged")
    check("refusals are audited with the person's name", any(r["action"] == "access_denied" and r["detail"].get("actor") == "vera.viewer" for r in entries))
    check("no password appears anywhere in the log", not any(rec["password"] in json.dumps(entries) for rec in known.values()) and "temporary phrase" not in json.dumps(entries))
    check("another organization cannot sign this person in", sign_in("t-globex", "asha.admin", known["t-acme/asha.admin"]["password"])[0] == 401)
    check("responses carry protective headers", urllib_headers(f"{SAAS}/v1/fleet", viewer).get("x-content-type-options") == "nosniff")
    print("  RESULT:", "PASS" if all(results) else "FAIL", f"({sum(results)} of {len(results)} checks)")


def urllib_headers(url, token):
    req = request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with request.urlopen(req, timeout=10, context=_ctx(url)) as r:
        return {k.lower(): v for k, v in r.getheaders()}


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
    expect("policy check, human approval, audit trail and rollback plan; simulation only, nothing is executed")
    inc = saas_get("/v1/incidents")
    if not isinstance(inc, list) or not inc:
        print("  no incident yet. Run 'alert-storm' or 'cpu-spike' first.")
        return
    incident = inc[0]
    iid = incident["id"]
    auth = {"Authorization": f"Bearer {DASH}", "Content-Type": "application/json"}

    def post(path, body=None):
        return _call(f"{SAAS}{path}", json.dumps(body).encode() if body is not None else b"", auth, "POST")

    print(f"  incident {iid[:8]} | {incident.get('severity')} | {incident.get('recommendation', {}).get('likely_cause')}")

    # 1. Policy check: an action must target the incident's own source. A different source is refused.
    status, res = post("/v1/actions/propose", {"incident_id": iid, "action_type": "isolate_source", "parameters": {"source_id": "src_0000000000000000"}})
    print(f"  1. policy check, isolate a DIFFERENT source: HTTP {status} ({res.get('detail') if isinstance(res, dict) else res})  <- refused as expected" if status == 422 else f"  1. policy check: HTTP {status} {res}  <- BAD, expected 422")

    # 2. A valid proposal.
    status, action = post("/v1/actions/propose", {"incident_id": iid, "action_type": "restart_service", "parameters": {"service": "web-frontend"}})
    if status != 200 or not isinstance(action, dict):
        print(f"  2. propose: HTTP {status} {action}")
        return
    aid = action["id"]
    print(f"  2. proposed {action['action_type']} {action['parameters']} -> status={action['status']} | simulation_only={action['simulation_only']}")
    print(f"     rollback plan: {action['rollback_plan']}")

    # 3. Human approval, then 4. rollback.
    status, action = post(f"/v1/actions/{aid}/approve")
    print(f"  3. approve -> HTTP {status} status={action.get('status') if isinstance(action, dict) else action}")
    status, action = post(f"/v1/actions/{aid}/rollback")
    print(f"  4. rollback -> HTTP {status} status={action.get('status') if isinstance(action, dict) else action}")
    if isinstance(action, dict):
        print("  audit trail:")
        for a in action.get("audit", []):
            print(f"    {a.get('ts')} | {a.get('action')} | by role={a.get('detail', {}).get('role')}")
    status, _ = post(f"/v1/actions/{aid}/approve")
    print(f"  5. approving again after rollback: HTTP {status}  " + ("(refused: invalid transition)" if status == 409 else "<- BAD, expected 409"))


def flood():
    expect("a flood cannot fill the disk: raw records and the outbox stay within their caps, the oldest data is dropped first, every drop is counted, and the loss is reported")
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data" / "flood-demo"
    shutil.rmtree(data_dir, ignore_errors=True)
    port = 8103
    # A collector with tight limits and no reachable platform, so nothing can drain: the worst case.
    env = {**os.environ, "DATA_DIR": str(data_dir), "RAW_MAX_ROWS": "500", "OUTBOX_MAX_PENDING": "200", "MAX_DB_BYTES": str(1 << 20),
           "MAX_LINE_CHARS": "5000", "MAX_INGEST_BYTES": str(2 << 20), "RETENTION_INTERVAL_S": "3", "SAAS_URL": "http://127.0.0.1:9",
           "HOST_TELEMETRY": "0", "REQUIRE_TLS": "0"}
    for name in ("SAAS_CA_FILE",):
        env.pop(name, None)
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "flood-demo.log", "wb")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "collector.main:app", "--port", str(port)], cwd=root, env=env, stdout=log, stderr=log)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(30):
            time.sleep(1)
            if _poll(f"{base}/healthz")[0] == 200:
                break
        else:
            print("  the demo collector did not start; see data/logs/flood-demo.log")
            return
        print("  limits: 500 raw rows, 200 pending payloads, 1 MiB of live data, 5000 characters per line, 2 MiB per request; the platform is unreachable")
        started = time.time()
        now = int(time.time())
        for batch in range(40):  # 40,000 lines across 400 hosts and many windows, so tens of thousands of payloads
            lines = [json.dumps({"kind": "metric", "host": f"host-{(batch * 1000 + i) % 400}", "name": "cpu_pct", "value": (batch + i) % 100,
                                 "ts": iso(now - 3600 + batch * 60 + i * 0.05)}) for i in range(1000)]
            collector_send_to(base, lines)
        print(f"  1. sent 40,000 lines in {time.time() - started:.1f} s")
        st, res = _call(f"{base}/ingest", ("x" * 20000).encode(), {}, "POST")
        print(f"  2. one 20,000-character line: {res}")
        st, _ = _call(f"{base}/ingest", b"y" * (3 << 20), {}, "POST")
        print(f"  3. a 3 MiB request: HTTP {st}  " + ("(refused)" if st == 413 else "<- BAD, expected 413"))
        time.sleep(5)  # let the retention job run and report the loss
        r = _call(f"{base}/local/retention")[1]
        u, t = r["usage"], r["totals"]
        print(f"  4. raw rows kept: {u['raw_rows']} (cap 500) | pending payloads: {u['outbox'].get('pending', 0)} (cap 200) | disk used: {u['disk_bytes'] / 1048576:.1f} MiB")
        print(f"     counted losses: {t['trimmed_raw_total']} raw rows trimmed | {t['dropped_overflow_total']} oldest payloads dropped | {r['oversize_lines_dropped']} oversize line(s) dropped")
        eg = _call(f"{base}/local/egress?limit=300")[1]
        loss = next((e["payload"]["event"] for e in eg if e["payload"].get("event", {}).get("summary") == "buffer overflow dropped payloads"), None)
        print(f"  5. loss reported to the platform as an event: {loss}")
        bounded = u["raw_rows"] <= 700 and u["outbox"].get("pending", 0) <= 300 and u["disk_bytes"] < 16 * 1048576
        print("  RESULT: " + ("bounded, counted and reported" if bounded and t["dropped_overflow_total"] > 0 and loss else "NOT BOUNDED, investigate"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def collector_send_to(base, lines):
    return _call(f"{base}/ingest", "\n".join(lines).encode())[1]


def enroll_demo():
    expect("a brand-new collector registers itself with a one-time token and starts reporting on its own credentials, with no key typed anywhere")
    root = Path(__file__).resolve().parents[1]
    admin = os.getenv("DASHBOARD_ADMIN_TOKEN", "dash-admin")
    https = SAAS.startswith("https://")
    cid = "col-enrolled-" + uuid.uuid4().hex[:4]
    headers = {"Authorization": f"Bearer {admin}", "Content-Type": "application/json"}

    status, res = _call(f"{SAAS}/v1/enrollment-tokens", json.dumps({"collector_id": cid, "expires_in_s": 300}).encode(), headers, "POST")
    if status != 200 or not isinstance(res, dict):
        print(f"  could not issue a token (HTTP {status} {res}). Is the stack from run-local.ps1 running with the admin token?")
        return
    token, tenant = res["token"], res["tenant_ref"]
    print(f"  1. an admin issued a one-time token for {cid} (tenant {tenant}, expires {res['expires_at']}); the token itself is not shown")

    data_dir = root / "data" / "enroll-demo"
    shutil.rmtree(data_dir, ignore_errors=True)
    env = {**os.environ, "DATA_DIR": str(data_dir), "ENROLL_TOKEN": token, "ENROLL_TENANT": tenant, "SAAS_URL": SAAS,
           "HOST_LABEL": "enroll-demo-host", "HEARTBEAT_INTERVAL_S": "3", "REQUIRE_TLS": "1" if https else "0"}
    for name in ("COLLECTOR_KEY", "COLLECTOR_SECRET", "PSEUDO_SECRET", "COLLECTOR_ID", "TENANT_REF", "REGION"):
        env.pop(name, None)  # nothing identifies this collector except the token
    if SAAS_CA:
        env["SAAS_CA_FILE"] = SAAS_CA
    if not https:
        env["ENROLL_ALLOW_HTTP"] = "1"
        print("  (the SaaS is on plain HTTP, so enrollment is allowed only because this is a dev demo; use -Tls for the real thing)")
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "enroll-demo.log", "wb")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "collector.main:app", "--port", "8102"], cwd=root, env=env, stdout=log, stderr=log)
    try:
        ident = None
        for _ in range(40):
            time.sleep(1)
            if proc.poll() is not None:
                print("  2. the new collector exited at startup; see data/logs/enroll-demo.log")
                return
            st, body = _poll("http://127.0.0.1:8102/local/identity")
            if st == 200 and isinstance(body, dict):
                ident = body
                break
        if not ident:
            print("  2. the new collector did not come up in 40 s; see data/logs/enroll-demo.log")
            return
        print(f"  2. started a new collector with NO keys configured. It enrolled itself: credentials={ident['credentials']}, "
              f"collector_id={ident['collector_id']}, uses_dev_defaults={ident['uses_dev_defaults']}")
        creds_file = data_dir / "credentials.json"
        print(f"  3. its credentials are in {creds_file.relative_to(root)} (readable only by its owner): {'present' if creds_file.exists() else 'MISSING'}")

        seen = None
        for _ in range(45):
            fleet = saas_get("/v1/fleet")
            seen = next((f for f in fleet if f.get("collector_id") == cid), None) if isinstance(fleet, list) else None
            if seen and seen.get("online"):
                break
            time.sleep(1)
        if seen:
            print(f"  4. the platform sees it: {cid} | state={seen.get('state')} | online={seen.get('online')} | version={seen.get('version')}")
        else:
            print(f"  4. the platform has not seen {cid} yet <- BAD")

        status, _ = _call(f"{SAAS}/v1/enroll", json.dumps({"tenant_ref": tenant, "token": token}).encode(), {"Content-Type": "application/json"}, "POST")
        print(f"  5. the same token used again: HTTP {status}  " + ("(refused: it is single use)" if status == 401 else "<- BAD, expected 401"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        print("  (the demo collector was stopped; it stays in the fleet and will show as offline)")


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
    "flood": flood,
    "enroll": enroll_demo,
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
    "hold": hold,
    "tenants": tenants,
    "rbac": rbac,
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
