"""Proof tools (E19): two independent checks of the privacy claim, each ending in a plain PASS or FAIL.

    python simulator/verify.py match      # does what the SaaS stored equal what the collector says it sent?
    python simulator/verify.py canary     # do planted secrets appear anywhere on the platform?
    python simulator/verify.py all        # both

Exit code: 0 = PASS, 1 = FAIL, 2 = INCOMPLETE (a required check could not run, so nothing is claimed).

MATCH compares the collector's egress log (what it queued and sent, with the SHA-256 it fixed at queue time) with the
payload the platform stored under the same ID, field by field. Differences, payloads missing at the platform, and
platform payloads the collector never sent are all reported.

CANARY plants fake secrets (password, API key, JWT, email, AWS key, username, host name, free text) in log lines sent to
the collector, waits until the resulting payloads are delivered, then searches every place the platform could hold them
for each canary and its encoded forms (JSON-escaped, URL-encoded, base64, lower case):
  - the collector's egress log           (everything that left)
  - the platform API                     (every list endpoint, plus per-payload detail and lineage)
  - the platform database                (every table, all tenants, read with the admin role; needs psql)
  - the platform and proxy logs
Two positive controls keep a PASS honest: the scanner must find a canary it is shown, and every canary must be found
in the collector's LOCAL raw store (so it really was received and is a fair test). If either fails the result is FAIL.

Needs the stack from scripts/run-local.ps1 (scripts/verify.ps1 sets the environment). Evidence is written to
docs/p3/evidence/verify-<UTC time>.md and .json.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scenarios as sc  # noqa: E402  (environment, HTTP helpers and TLS handling shared with the scenarios)
from collector.outbox import digest_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "p3" / "evidence"
ADMIN_DB = os.getenv("ADMIN_DATABASE_URL", "postgresql://postgres@localhost:5433/signal")


# ---------------------------------------------------------------- pure helpers (unit tested)
def normalize_ts(value) -> str:
    """The platform stores timestamps at microsecond precision; compare on that form."""
    if not isinstance(value, str):
        return str(value)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def normalized(payload: dict) -> dict:
    out = dict(payload)
    if "event_ts_utc" in out:
        out["event_ts_utc"] = normalize_ts(out["event_ts_utc"])
    return out


def differing_fields(sent: dict, stored: dict) -> list[str]:
    """Names of fields that differ between what was sent and what was stored (timestamp precision ignored)."""
    a, b = normalized(sent), normalized(stored)
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def match_summary(egress_rows: list[dict], stored: dict[str, dict | None], platform_ids_for_collector: list[str] | None = None) -> dict:
    """Pure comparison. `stored` maps payload_id -> the platform's copy (None when the platform has no such payload)."""
    sent = [r for r in egress_rows if r["status"] == "sent"]
    others: dict[str, int] = {}
    for r in egress_rows:
        if r["status"] != "sent":
            others[r["status"]] = others.get(r["status"], 0) + 1
    missing, mismatched, bad_digest, ok = [], [], [], 0
    for r in sent:
        pid, payload = r["payload_id"], r["payload"]
        if r.get("digest") and digest_of(payload) != r["digest"]:
            bad_digest.append(pid)  # the egress log itself no longer matches the digest fixed at queue time
        platform_copy = stored.get(pid)
        if platform_copy is None:
            missing.append(pid)
            continue
        diff = differing_fields(payload, platform_copy)
        if diff:
            mismatched.append({"payload_id": pid, "fields": diff})
        elif digest_of(normalized(payload)) != digest_of(normalized(platform_copy)):
            mismatched.append({"payload_id": pid, "fields": ["(digest)"]})
        else:
            ok += 1
    known = {r["payload_id"] for r in egress_rows}
    unexplained = sorted(set(platform_ids_for_collector or []) - known)
    passed = bool(sent) and not missing and not mismatched and not bad_digest and not unexplained
    return {
        "payloads_sent_per_collector_log": len(sent),
        "identical_at_platform": ok,
        "missing_at_platform": len(missing),
        "missing_examples": missing[:5],
        "different_at_platform": len(mismatched),
        "different_examples": mismatched[:5],
        "egress_log_digest_mismatch": len(bad_digest),
        "at_platform_but_never_sent_by_collector": len(unexplained),
        "unexplained_examples": unexplained[:5],
        "not_sent_by_status": others,
        "verdict": "PASS" if passed else ("INCOMPLETE" if not sent else "FAIL"),
    }


def variants(value: str) -> dict[str, str]:
    """The ways a secret could show up if something re-encoded it on the way."""
    raw = value.encode()
    return {
        "plain": value,
        "lowercase": value.lower(),
        "json-escaped": json.dumps(value)[1:-1],
        "url-encoded": urllib.parse.quote(value, safe=""),
        "base64": base64.b64encode(raw).decode().rstrip("="),
        "base64-url": base64.urlsafe_b64encode(raw).decode().rstrip("="),
    }


def scan_text(text: str, canaries: dict[str, str]) -> list[dict]:
    """Which canaries (label, variant) appear in this text. The text is also searched lower-cased."""
    low = text.lower()
    hits = []
    for label, value in canaries.items():
        for name, needle in variants(value).items():
            if needle and (needle in text or needle.lower() in low):
                hits.append({"canary": label, "form": name})
                break
    return hits


def make_canaries(tag: str) -> dict[str, str]:
    """Fake secrets, unique to this run so an old run can never be mistaken for this one."""
    jwt_body = base64.urlsafe_b64encode(json.dumps({"sub": f"canary-{tag}"}).encode()).decode().rstrip("=")
    return {
        "password": f"Cn4ry!{tag}Pw",
        "api_key": f"sk_live_{tag}A9b8C7d6E5f4",
        "jwt": f"eyJhbGciOiJIUzI1NiJ9.{jwt_body}.sig{tag}",
        "email": f"canary.{tag}@example-canary.test",
        "aws_key": "AKIA" + (tag.upper() * 3)[:16],
        "username": f"canaryuser_{tag}",
        "hostname": f"canary-host-{tag}",
        "free_text": f"CANARY-FREETEXT-{tag}",
    }


def canary_lines(tag: str, c: dict[str, str]) -> list[str]:
    """The same secrets in four log formats, plus a failed-login burst naming the canary user."""
    now = sc.iso(time.time() - 8)
    host = c["hostname"]
    lines = [
        json.dumps({"kind": "log", "ts": now, "host": host, "message": f"login ok password={c['password']} api_key={c['api_key']}", "level": "info"}),
        json.dumps({"kind": "log", "ts": now, "host": host, "message": f"Authorization: Bearer {c['jwt']}", "user": c["username"], "contact": c["email"], "level": "warn"}),
        f'ts={now} host={host} msg="aws key {c["aws_key"]} owner {c["email"]} note {c["free_text"]}"',
        f"<34>1 {now} {host} app 42 - - token={c['api_key']} user={c['username']} {c['free_text']}",
        f"{now} {host} request failed: {c['free_text']} password: {c['password']}",
    ]
    lines += [f'ts={now} host={host} msg="Failed password for invalid user {c["username"]} from 203.0.113.{i + 1} port 22"' for i in range(8)]
    lines += sc.metric_lines(host, "cpu_utilization_percent", 41.0, n=3, per_window=2)
    return lines


# ---------------------------------------------------------------- reading both sides
def collector_get(path: str):
    return sc._call(f"{sc.COLLECTOR}{path}")


def collector_egress(limit: int = 5000) -> list[dict]:
    status, body = collector_get(f"/local/egress?limit={limit}")
    if status != 200 or not isinstance(body, list):
        raise RuntimeError(f"cannot read the collector egress log (HTTP {status}); is the stack running?")
    return body


def platform_observation(payload_id: str) -> dict | None:
    status, body = sc._call(f"{sc.SAAS}/v1/objects/observation/{payload_id}", headers={"Authorization": f"Bearer {sc.DASH}"})
    if status == 200 and isinstance(body, dict):
        return body.get("properties")
    return None


def platform_observation_ids(collector_id: str) -> list[str]:
    status, body = sc._call(f"{sc.SAAS}/v1/objects/observation", headers={"Authorization": f"Bearer {sc.DASH}"})
    if status != 200 or not isinstance(body, list):
        return []
    return [o["id"] for o in body if o.get("properties", {}).get("collector_id") == collector_id]


# ---------------------------------------------------------------- MATCH
def run_match(max_rows: int = 300) -> dict:
    rows = collector_egress()
    sent = [r for r in rows if r["status"] == "sent"][:max_rows]
    with ThreadPoolExecutor(max_workers=8) as pool:
        copies = list(pool.map(lambda r: platform_observation(r["payload_id"]), sent))
    stored = {r["payload_id"]: c for r, c in zip(sent, copies)}
    collector_id = next((r["payload"].get("collector_id") for r in rows if r.get("payload")), None)
    ids = platform_observation_ids(collector_id) if collector_id else []
    # The platform lists its newest 500. Only judge IDs that are not older than the oldest row the collector still keeps.
    oldest = min((normalize_ts(r["payload"]["event_ts_utc"]) for r in rows), default=None)
    listing = {}
    if ids and oldest:
        status, body = sc._call(f"{sc.SAAS}/v1/objects/observation", headers={"Authorization": f"Bearer {sc.DASH}"})
        listing = {o["id"]: normalize_ts(o["properties"].get("event_ts_utc", "")) for o in (body or []) if isinstance(o, dict)}
        ids = [i for i in ids if listing.get(i, "") >= oldest]
    complete = len(rows) < 5000
    result = match_summary([r for r in rows if r["payload_id"] in stored or r["status"] != "sent"], stored, ids if complete else None)
    result["checked_newest"] = len(sent)
    return {"check": "match", **result}


# ---------------------------------------------------------------- CANARY
def psql_path() -> str | None:
    if os.getenv("PG_BIN") and Path(os.environ["PG_BIN"], "psql.exe").exists():
        return str(Path(os.environ["PG_BIN"], "psql.exe"))
    found = shutil.which("psql")
    if found:
        return found
    cands = sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\psql.exe"), reverse=True)
    return cands[0] if cands else None


def database_text() -> tuple[str, int] | None:
    """Every row of every table as text, all tenants (admin role). None when the database cannot be read."""
    psql = psql_path()
    if not psql:
        return None

    def run(sql: str) -> str | None:
        try:
            out = subprocess.run([psql, ADMIN_DB, "-At", "-c", sql], capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout if out.returncode == 0 else None

    tables = run("SELECT quote_ident(table_schema)||'.'||quote_ident(table_name) FROM information_schema.tables "
                 "WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema')")
    if tables is None:
        return None
    names = [t for t in tables.split() if t]
    chunks = []
    for t in names:
        data = run(f"SELECT x::text FROM {t} x")
        if data is None:
            return None
        chunks.append(data)
    return "\n".join(chunks), len(names)


def api_sweep(payload_ids: list[str]) -> tuple[str, int]:
    """Everything the dashboard role can read, as one text blob."""
    auth = {"Authorization": f"Bearer {sc.DASH}"}
    paths = ["/healthz", "/v1/fleet", "/v1/metrics?limit=10000", "/v1/incidents", "/v1/health/history", "/v1/proof", "/v1/ontology", "/v1/actions", "/v1/noise"]
    status, onto = sc._call(f"{sc.SAAS}/v1/ontology", headers=auth)
    kinds = list(onto.get("types", {})) if status == 200 and isinstance(onto, dict) else ["tenant", "collector", "source", "observation", "incident", "recommendation", "action"]
    paths += [f"/v1/objects/{k}" for k in kinds]
    paths += [f"/v1/objects/observation/{i}" for i in payload_ids] + [f"/v1/lineage/payload/{i}" for i in payload_ids]
    with ThreadPoolExecutor(max_workers=8) as pool:
        bodies = list(pool.map(lambda p: sc._call(f"{sc.SAAS}{p}", headers=auth)[1], paths))
    return "\n".join(json.dumps(b, sort_keys=True) if not isinstance(b, str) else b for b in bodies), len(paths)


def log_text() -> tuple[str, int]:
    chunks, n = [], 0
    for path in glob.glob(str(ROOT / "data" / "logs" / "*.log")):
        name = Path(path).name
        if name.startswith(("saas", "lb", "pg", "measure")) or name in ("enroll-demo.log", "flood-demo.log"):
            try:
                chunks.append(Path(path).read_text(encoding="utf-8", errors="replace"))
                n += 1
            except OSError:
                pass
    return "\n".join(chunks), n


def wait_for_delivery(before: set[str], timeout: float = 60.0) -> list[dict]:
    """New payloads created since `before`, once none of them is still waiting. Empty if nothing new appeared."""
    deadline = time.time() + timeout
    new: list[dict] = []
    while time.time() < deadline:
        time.sleep(1.5)
        rows = collector_egress()
        new = [r for r in rows if r["payload_id"] not in before]
        if new and all(r["status"] != "pending" for r in new) and time.time() > deadline - timeout + 12:
            break
    return new


def run_canary() -> dict:
    tag = uuid.uuid4().hex[:8]
    canaries = make_canaries(tag)
    surfaces: list[dict] = []
    controls: list[dict] = []

    # Control 1: the scanner can find what it is shown, in every encoded form.
    seen = {label: bool(scan_text(f"prefix {v} suffix", {label: v})) for label, v in canaries.items()}
    seen |= {label + " (json-escaped)": bool(scan_text(json.dumps({"x": v}), {label: v})) for label, v in canaries.items()}
    controls.append({"name": "scanner finds a planted canary (plain and JSON-escaped)", "passed": all(seen.values())})

    before = {r["payload_id"] for r in collector_egress()}
    print(f"  planting {len(canaries)} canaries on host {canaries['hostname']} ...")
    sc.collector_send(canary_lines(tag, canaries))
    new = wait_for_delivery(before)
    produced = [r["payload_id"] for r in new]

    # Control 2: every canary really reached the collector (local raw store), so the test is fair.
    status, raw = collector_get("/local/raw?limit=500")
    raw_text = json.dumps(raw) if status == 200 else ""
    local_hits = {h["canary"] for h in scan_text(raw_text, canaries)}
    not_stored = sorted(set(canaries) - local_hits)
    controls.append({"name": "every canary was received and is visible in the collector's local raw store", "passed": not not_stored, "detail": not_stored})
    controls.append({"name": "the canary lines produced payloads to check", "passed": bool(produced), "detail": f"{len(produced)} payload(s)"})

    # Required surfaces.
    egress_text = json.dumps(collector_egress(), sort_keys=True)
    surfaces.append(_surface("collector egress log (everything that left)", egress_text, canaries, required=True))
    pids = [r["payload_id"] for r in new]
    # Also scan the other payloads of the run window: everything the platform holds for the tenant.
    api_text, n_paths = api_sweep(pids)
    surfaces.append(_surface(f"platform API ({n_paths} endpoints, dashboard role)", api_text, canaries, required=True))
    db = database_text()
    if db is None:
        surfaces.append({"name": "platform database (all tables, all tenants)", "status": "SKIPPED", "required": True, "note": "psql not found or the database could not be read; set PG_BIN or ADMIN_DATABASE_URL"})
    else:
        surfaces.append(_surface(f"platform database ({db[1]} tables, all tenants)", db[0], canaries, required=True))
    logs, n_logs = log_text()
    surfaces.append(_surface(f"platform and proxy logs ({n_logs} files)", logs, canaries, required=False) if n_logs else
                    {"name": "platform and proxy logs", "status": "SKIPPED", "required": False, "note": "no log files found"})

    # Control 3: each required surface was really read. A scan of an empty or unreadable surface proves nothing,
    # so every one must contain a value that is known to be there (this collector's own ID).
    known = next((r["payload"].get("collector_id") for r in collector_egress() if r.get("payload")), "")
    texts = {"collector egress log": egress_text, "platform API": api_text}
    if db is not None:
        texts["platform database"] = db[0]
    unread = sorted(name for name, text in texts.items() if not known or known not in text)
    controls.append({"name": "every scanned surface contains a known real value (it was actually read)", "passed": not unread, "detail": unread})

    failed_surface = any(s["status"] == "FAIL" for s in surfaces)
    failed_control = any(not c["passed"] for c in controls)
    incomplete = any(s["status"] == "SKIPPED" and s["required"] for s in surfaces)
    verdict = "FAIL" if failed_surface or failed_control else "INCOMPLETE" if incomplete else "PASS"
    return {
        "check": "canary", "run_tag": tag,
        "canaries_planted": {k: f"{len(v)} characters" for k, v in canaries.items()},
        "payloads_produced_by_the_run": len(produced),
        "controls": controls, "surfaces": surfaces, "verdict": verdict,
    }


def _surface(name: str, text: str, canaries: dict[str, str], required: bool) -> dict:
    hits = scan_text(text, canaries)
    return {"name": name, "bytes_scanned": len(text.encode("utf-8", errors="replace")), "hits": hits, "required": required, "status": "FAIL" if hits else "PASS"}


# ---------------------------------------------------------------- output
def render(results: list[dict]) -> str:
    out = ["# Proof run", "", f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for r in results:
        out += [f"## {r['check'].upper()}: **{r['verdict']}**", ""]
        if r["check"] == "match":
            for k, v in r.items():
                if k not in ("check", "verdict"):
                    out.append(f"- {k}: {v}")
        else:
            out.append(f"- run tag {r['run_tag']}; {r['payloads_produced_by_the_run']} payload(s) produced; canaries: " + ", ".join(r["canaries_planted"]))
            out += ["", "Positive controls:", ""]
            out += [f"- {'PASS' if c['passed'] else 'FAIL'}: {c['name']}" + (f" ({c['detail']})" if c.get("detail") else "") for c in r["controls"]]
            out += ["", "Surfaces searched (each canary in plain, lower-case, JSON-escaped, URL-encoded and base64 form):", ""]
            for s in r["surfaces"]:
                extra = f"{s.get('bytes_scanned', 0)} bytes, {len(s.get('hits', []))} hit(s)" if s["status"] != "SKIPPED" else s["note"]
                out.append(f"- {s['status']}: {s['name']} ({extra})")
                for h in s.get("hits", []):
                    out.append(f"  - FOUND `{h['canary']}` as {h['form']}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["match", "canary", "all"])
    ap.add_argument("--max", type=int, default=300, help="newest sent payloads to compare for match")
    args = ap.parse_args()
    results = []
    try:
        if args.what in ("match", "all"):
            print("MATCH: comparing the collector's egress log with what the platform stored ...")
            results.append(run_match(args.max))
        if args.what in ("canary", "all"):
            print("CANARY: planting secrets and searching the platform ...")
            results.append(run_canary())
    except RuntimeError as exc:
        print(f"INCOMPLETE: {exc}")
        return 2
    text = render(results)
    print("\n" + text)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (EVIDENCE / f"verify-{stamp}.md").write_text(text, encoding="utf-8")
    (EVIDENCE / f"verify-{stamp}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    verdicts = [r["verdict"] for r in results]
    overall = "FAIL" if "FAIL" in verdicts else "INCOMPLETE" if "INCOMPLETE" in verdicts else "PASS"
    print(f"OVERALL: {overall}   (evidence: docs/p3/evidence/verify-{stamp}.md)")
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2}[overall]


if __name__ == "__main__":
    sys.exit(main())
