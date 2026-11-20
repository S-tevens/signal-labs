"""Stream check (E26): dry-run a sample of the organizers' stream through the collector's parsers and mapping.

    python simulator/stream_check.py sample.txt            # a file of sample lines (any supported format)
    python simulator/stream_check.py - < sample.txt        # from stdin
    python simulator/stream_check.py sample.txt --json     # machine-readable

Nothing is sent anywhere and nothing is stored: it only tells you what the collector would make of each line. For every
line it reports the detected format, the host, the metric name and value (after the aliases and unit conversions in
collector/mapping.yaml), whether a time could be read, and which sensitive patterns were found. At the end it lists what
did NOT map (unknown metric names, numeric fields that are ignored, lines with no readable time) and the lines to add to
collector/mapping.yaml. Exit code: 0 = READY (at least one record would be accepted and nothing numeric is being ignored),
1 = NEEDS MAPPING, 2 = nothing usable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import mapping  # noqa: E402
from collector.config import Config  # noqa: E402
from collector.outbox import LocalStore  # noqa: E402
from collector.parsers import parse_records  # noqa: E402
from collector.pipeline import Pipeline  # noqa: E402
from collector.pull import expand  # noqa: E402
from collector.redact import redact  # noqa: E402
from collector.schema import METRIC_NAMES  # noqa: E402
from collector.mapping import flatten  # noqa: E402

GUESS = [("cpu", "cpu_pct"), ("mem", "mem_pct"), ("disk", "disk_pct"), ("lat", "latency_ms"), ("rtt", "latency_ms"), ("loss", "packet_loss_pct"),
         ("band", "bandwidth_mbps"), ("throughput", "bandwidth_mbps"), ("bw", "bandwidth_mbps"), ("net", "bandwidth_mbps"), ("rx", "bandwidth_mbps"), ("tx", "bandwidth_mbps"), ("bps", "bandwidth_mbps"), ("alive", "service_up"), ("up", "service_up"), ("status", "service_up")]
_KV = re.compile(r'(\w+)=("[^"]*"|\S+)')


def guess(name: str) -> str | None:
    """The most likely canonical metric for a field name, with a unit scale when the name says the unit differs."""
    low = name.lower()
    canon = next((c for key, c in GUESS if key in low), None)
    if canon is None:
        return None
    scale = None
    if canon == "bandwidth_mbps":
        scale = 0.001 if "kbps" in low else 1000 if "gbps" in low else 0.000001 if re.search(r"(?<![kmg])bps", low) else None
    elif canon == "latency_ms":
        scale = 1000 if re.search(r"(_s|_sec|seconds)$", low) else 0.001 if low.endswith("_us") else None
    elif canon in ("cpu_pct", "mem_pct", "disk_pct", "packet_loss_pct") and ("ratio" in low or "fraction" in low):
        scale = 100
    return canon if scale is None else "{name: %s, scale: %s}" % (canon, scale)


def fields_of(line: str, header: list[str] | None) -> dict:
    """The raw field names and values in a line, to spot numeric columns the mapping would ignore."""
    s = line.strip()
    if s.startswith("{"):
        try:
            data = json.loads(s)
            return flatten(data)[0] if isinstance(data, dict) else {}
        except ValueError:
            return {}
    if header and "," in s:
        cells = [c.strip().strip('"') for c in s.split(",")]
        return dict(zip(header, cells)) if len(cells) == len(header) else {}
    return {k: v.strip('"') for k, v in _KV.findall(s)}


def analyse(lines: list[str]) -> dict:
    m = mapping.get()
    pipe = Pipeline(Config(data_dir=":memory:", host_telemetry=False), LocalStore(":memory:"))
    state: dict = {}
    rows, formats, hosts, rules = [], Counter(), Counter(), Counter()
    unmapped, ignored, no_time = Counter(), Counter(), 0
    accepted = dropped = 0
    known = m.known_fields()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("{") and m.looks_like_header(line):
            state["csv_header"] = [c.strip().strip('"') for c in line.split(",")]
            rows.append({"line": line[:90], "note": "CSV header: columns set"})
            continue
        _, fired = redact(line, pipe.policy.redaction_rules)
        rules.update(set(fired))
        for k, v in fields_of(line, state.get("csv_header")).items():
            try:
                float(v)
                numeric = not isinstance(v, bool)
            except (TypeError, ValueError):
                numeric = False
            if numeric and str(k).lower() not in known:
                ignored[str(k)] += 1
        for r in parse_records(line, state.get("csv_header")):
            formats[r.get("format")] += 1
            hosts[r.get("host")] += 1
            if not r.get("ts"):
                no_time += 1
            note, ok = "", True
            if r["kind"] == "metric":
                name = r.get("name")
                try:
                    value = float(r.get("value"))
                except (TypeError, ValueError):
                    value, ok, note = None, False, "value is not a number"
                if ok and name not in METRIC_NAMES:
                    ok, note = False, f"unknown metric name {name!r}"
                    unmapped[str(name)] += 1
                label = f"metric {name} = {value}"
            else:
                label = "log (text stays local; only an auth-failure count can leave)"
            accepted, dropped = accepted + ok, dropped + (not ok)
            rows.append({"line": line[:90], "format": r.get("format"), "host": r.get("host"), "result": label, "time": r.get("ts") or "none, arrival time is used",
                         "accepted": ok, "note": note, "sensitive": sorted(set(fired))})
    suggestions = {n: guess(n) for n in unmapped} | {n: guess(n) for n in ignored}
    verdict = "NOTHING USABLE" if not accepted else "NEEDS MAPPING" if (unmapped or ignored) else "READY"
    return {"lines": len([x for x in lines if x.strip()]), "records_accepted": accepted, "records_dropped": dropped, "formats": dict(formats),
            "hosts": dict(hosts.most_common(10)), "sensitive_patterns_found": dict(rules), "records_without_a_time": no_time,
            "unknown_metric_names": dict(unmapped), "numeric_fields_ignored": dict(ignored), "suggested_mapping": suggestions, "verdict": verdict, "rows": rows}


def render(res: dict, show: int = 12) -> str:
    out = [f"Checked {res['lines']} line(s): {res['records_accepted']} record(s) would be accepted, {res['records_dropped']} dropped.", ""]
    for r in res["rows"][:show]:
        out.append(f"  {r['line']}" if "note" in r and "format" not in r else f"  [{r['format']}] host={r['host']}  {r['result']}  time={r['time']}" + (f"  DROPPED: {r['note']}" if not r["accepted"] else "") + (f"  sensitive: {', '.join(r['sensitive'])}" if r["sensitive"] else ""))
    if len(res["rows"]) > show:
        out.append(f"  ... and {len(res['rows']) - show} more")
    out += ["", f"Formats seen: {res['formats'] or 'none'}", f"Hosts seen: {list(res['hosts']) or 'none'}",
            f"Sensitive patterns found (they stay local): {list(res['sensitive_patterns_found']) or 'none'}",
            f"Records with no readable time (arrival time is used instead): {res['records_without_a_time']}"]
    if res["unknown_metric_names"] or res["numeric_fields_ignored"]:
        out += ["", "These did not map. Add the ones that are metrics to collector/mapping.yaml under `metrics:`"
                " (add scale/offset if the unit differs, for example {name: latency_ms, scale: 1000} for seconds):"]
        for name in {**res["unknown_metric_names"], **res["numeric_fields_ignored"]}:
            canon = res["suggested_mapping"].get(name)
            out.append(f"    {name}: {canon}" if canon else f"    # {name}: ??? (no obvious match; one of {', '.join(METRIC_NAMES)})")
    out += ["", f"VERDICT: {res['verdict']}"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sample", help="file of sample lines, or - for stdin")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=5000, help="lines to read")
    a = ap.parse_args()
    text = sys.stdin.read() if a.sample == "-" else Path(a.sample).read_text(encoding="utf-8", errors="replace")
    res = analyse(expand(text).splitlines()[: a.limit])
    print(json.dumps(res, indent=2) if a.json else render(res))
    return {"READY": 0, "NEEDS MAPPING": 1, "NOTHING USABLE": 2}[res["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
