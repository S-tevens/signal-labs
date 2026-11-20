"""Trace one payload end to end (E27): raw record on the collector -> the exact payload that left -> the platform's
stored observation -> the incident and recommendation it fed.

    python simulator/trace.py <payload_id>             # trace an existing payload
    python simulator/trace.py --latest                 # the newest payload that was sent
    python simulator/trace.py --demo                   # plant a test secret and a failed-login burst, then trace the result
    python simulator/trace.py <payload_id> --show-secrets   # reveal sensitive spans (they are masked by default)

Each hop prints PASS or FAIL. Sensitive spans in raw records are masked so the output, and the evidence file written to
docs/p3/evidence/trace-*.md, never hold a secret. The platform copy is compared field by field with what the collector
queued; the platform widens timestamps to microseconds, so this is field equality, not proof of identical wire bytes.
An ordinary metric usually feeds no incident; that is reported, not failed, unless the run expects one (--demo does).
Exit code: 0 = every hop passed, 1 = a hop failed, 2 = could not run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenarios as sc  # noqa: E402
import verify  # noqa: E402  (field comparison and the digest rule are shared with the proof tools)

EVIDENCE = verify.EVIDENCE
AUTH = {"Authorization": f"Bearer {sc.DASH}"}


# ---------------------------------------------------------------- pure helpers (unit tested)
def mask(text: str, spans: list[dict], reveal: bool = False) -> str:
    """Replace each sensitive span with [rule:N chars]. Overlapping spans are merged first."""
    if reveal or not spans:
        return text
    merged: list[list] = []
    for s in sorted(spans, key=lambda s: s["start"]):
        if merged and s["start"] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], s["end"])
            merged[-1][2].append(s["rule"])
        else:
            merged.append([s["start"], s["end"], [s["rule"]]])
    out, pos = [], 0
    for start, end, rules in merged:
        out.append(text[pos:start])
        out.append(f"[{'+'.join(dict.fromkeys(rules))}:{end - start} chars]")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def leaked(payload: dict, raw: list[dict]) -> list[str]:
    """Rules whose sensitive value (taken from the raw record's spans) appears anywhere in the payload text."""
    blob = json.dumps(payload)
    found = []
    for r in raw:
        for s in r.get("spans", []):
            value = r["text"][s["start"]:s["end"]]
            if len(value) >= 4 and value in blob:
                found.append(s["rule"])
    return sorted(set(found))


def summarize_incident(incident: dict, payload_id: str) -> dict:
    props = incident.get("properties", incident)
    rec = props.get("recommendation") or {}
    mine = [s for s in props.get("signals", []) if s.get("payload_id") == payload_id]
    return {
        "incident_id": incident.get("id"),
        "severity": props.get("severity"),
        "source_id": props.get("source_id"),
        "signals_from_this_payload": [{k: s.get(k) for k in ("signal", "value", "why", "method", "severity") if k in s} for s in mine],
        "signals_in_incident": len(props.get("signals", [])),
        "recommendation": {k: v for k, v in rec.items() if isinstance(v, (str, int, float))} or None,
    }


# ---------------------------------------------------------------- the four hops
def hop_source(lineage: dict, reveal: bool) -> tuple[bool, list[str]]:
    raw = lineage.get("raw", [])
    lines = [f"payload {lineage['payload_id']} was made from {lineage.get('raw_total', len(raw))} raw record(s) held only on the collector"]
    for r in raw[:3]:
        lines.append(f"  raw #{r['id']} (received {datetime.fromtimestamp(r['received_at'], timezone.utc).strftime('%H:%M:%S')} UTC): "
                     + mask(r["text"][:200], r.get("spans", []), reveal))
    rules = sorted({s["rule"] for r in raw for s in r.get("spans", [])})
    lines.append(f"  sensitive patterns found locally: {', '.join(rules) if rules else 'none'}")
    return bool(raw), lines


def hop_outgoing(lineage: dict) -> tuple[bool, list[str]]:
    payload = lineage["payload"]
    digest_ok = verify.digest_of(payload) == lineage.get("digest")
    leaks = leaked(payload, lineage.get("raw", []))
    sent = f"sent at {datetime.fromtimestamp(lineage['sent_at'], timezone.utc).strftime('%H:%M:%S')} UTC" if lineage.get("sent_at") else "not sent yet"
    lines = [f"status {lineage['status']} ({sent})",
             f"SHA-256 of the exact bytes {lineage.get('digest')} {'(recomputed, matches)' if digest_ok else '(DOES NOT MATCH the stored payload)'}",
             "fields that left: " + ", ".join(sorted(payload)),
             f"sensitive values from the raw record found in the payload: {leaks if leaks else 'none'}"]
    return digest_ok and not leaks, lines


def hop_received(payload: dict, stored: dict | None) -> tuple[bool, list[str]]:
    if stored is None:
        return False, ["the platform has no observation with this ID (not delivered yet, or a different tenant)"]
    diff = verify.differing_fields(payload, stored)
    same = verify.digest_of(verify.normalized(payload)) == verify.digest_of(verify.normalized(stored))
    lines = [f"found in the tenant's observations; fields compared: {len(payload)}; differing: {diff if diff else 'none'}",
             f"digest of the normalized forms {'equal' if same else 'DIFFERENT'} (timestamp precision ignored; not a wire-byte comparison)"]
    return not diff and same, lines


def hop_incident(payload_id: str, expect: bool) -> tuple[bool, list[str]]:
    code, lin = sc._call(f"{sc.SAAS}/v1/lineage/payload/{payload_id}", headers=AUTH)
    incidents = lin.get("incidents", []) if code == 200 and isinstance(lin, dict) else []
    if not incidents:
        return (not expect), ["no retained incident signal references this payload" + (" (expected one)" if expect else " (normal for an ordinary measurement)")]
    lines = []
    for m in incidents[:2]:
        code, inc = sc._call(f"{sc.SAAS}/v1/objects/incident/{m['incident_id']}", headers=AUTH)
        s = summarize_incident(inc if code == 200 else {"id": m["incident_id"], "properties": {"signals": m["signals"]}}, payload_id)
        lines.append(f"incident {s['incident_id']}: severity {s['severity']}, {s['signals_in_incident']} signal(s) in total")
        for sig in s["signals_from_this_payload"]:
            lines.append(f"  signal from this payload: {sig}")
        lines.append(f"  recommendation: {json.dumps(s['recommendation']) if s['recommendation'] else 'none shown'}")
    lines.append("  this is a recommendation from rules and statistics, not proof of a root cause")
    return True, lines


# ---------------------------------------------------------------- driver
def fetch_lineage(payload_id: str) -> dict:
    code, body = sc._call(f"{sc.COLLECTOR}/local/lineage/{payload_id}?max_raw=20")
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"the collector has no payload {payload_id} (HTTP {code})")
    return body


def demo_payload() -> str:
    """Send a failed-login burst containing a test secret on a unique host, and return the burst's payload ID."""
    tag = uuid.uuid4().hex[:6]
    host, password = f"trace-demo-{tag}", f"Tr4ce!{tag}Pw"
    before = {e["payload_id"] for e in verify.collector_egress()}
    now = sc.iso(time.time() - 6)
    lines = [f'ts={now} host={host} msg="Failed password for invalid user admin from 203.0.113.{i + 1} port 22 password={password}"' for i in range(30)]
    print(f"  injecting 30 failed logins on {host}; each line carries a test password ...")
    sc.collector_send(lines)
    deadline = time.time() + 40
    while time.time() < deadline:
        time.sleep(1.5)
        for e in verify.collector_egress():
            if e["payload_id"] in before or "event" not in e["payload"]:
                continue
            lin = fetch_lineage(e["payload_id"])
            if any(password in r["text"] for r in lin.get("raw", [])) and lin["status"] == "sent":
                time.sleep(3)  # let the platform finish correlating
                return e["payload_id"]
    raise RuntimeError("the demo burst did not become a sent payload in time")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payload_id", nargs="?")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--show-secrets", action="store_true")
    args = ap.parse_args()
    try:
        if args.demo:
            pid = demo_payload()
        elif args.latest:
            sent = [e for e in verify.collector_egress(200) if e["status"] == "sent"]
            if not sent:
                raise RuntimeError("no sent payload yet")
            pid = sent[0]["payload_id"]
        elif args.payload_id:
            pid = args.payload_id
        else:
            ap.print_help()
            return 2
        lineage = fetch_lineage(pid)
    except RuntimeError as exc:
        print(f"cannot trace: {exc}")
        return 2
    stored = verify.platform_observation(pid)
    hops = [
        ("1. Source: raw record on the collector (local only)", *hop_source(lineage, args.show_secrets)),
        ("2. Outgoing: the exact payload that left", *hop_outgoing(lineage)),
        ("3. Received: the platform's stored observation", *hop_received(lineage["payload"], stored)),
        ("4. Incident and recommendation", *hop_incident(pid, expect=args.demo)),
    ]
    out = [f"# Trace of payload {pid}", "", f"UTC {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}; tenant {lineage['payload'].get('tenant_ref')}, "
           f"collector {lineage['payload'].get('collector_id')}, source {lineage['payload'].get('source_id')}", ""]
    for title, ok, lines in hops:
        out += [f"## {title}: **{'PASS' if ok else 'FAIL'}**", ""] + [f"- {x}" if not x.startswith("  ") else f"  {x.strip()}" for x in lines] + [""]
    ok_all = all(h[1] for h in hops)
    out.append(f"**RESULT: {'PASS' if ok_all else 'FAIL'}**")
    text = "\n".join(out)
    print("\n" + text)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / f"trace-{pid[:8]}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.md"
    path.write_text(text, encoding="utf-8")
    print(f"(evidence: {path.relative_to(verify.ROOT)})")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
