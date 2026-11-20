"""Scenario check (E28): a normal baseline plus injected scenarios, each with an expected and an actual result, and the
false and missed alerts counted over a stated window.

    python simulator/scenario_check.py                # about 2.5 minutes
    python simulator/scenario_check.py --warmup 40 --inject 15 --seed 3

Everything runs at once on separate hosts so the correlation window cannot merge unrelated scenarios:
  decoy hosts    steady, normal traffic for the whole run. Any incident on them is a FALSE alarm.
  scenario hosts steady for the warm-up (also counted as normal: an alert there before the injection is a false alarm),
                 then one thing is injected for --inject seconds, then steady again.
The expected result is written down before anything is sent. A scenario passes when its expected signal(s) appear on
its own source, nothing else is flagged there after the injection, and the first alert is visible within 15 s.

Definitions (also written into the evidence file):
  false alarm  an alert (signal) on a decoy host at any time, or on a scenario host before its injection.
  missed       an expected signal that never appeared on the scenario's source.
  extra        a signal on the scenario's source after the injection that was not expected.
  grouped      alerts of one source that ended up in the same incident (alert_count per incident).
A quiet short run is not a general false-alarm rate: the denominator is printed, and it is small.
Recovery (health returning to normal) is not judged here.
Evidence: docs/p3/evidence/scenarios-<UTC time>.md and .json. Exit code 0 = all passed, 1 = something failed.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scenarios as sc  # noqa: E402
from collector.redact import pseudonym  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "p3" / "evidence"
ALERT_TARGET_S = 15.0
BASELINE = {"cpu_pct": (35, 5), "mem_pct": (55, 4), "bandwidth_mbps": (120, 25), "latency_ms": (40, 6), "disk_pct": (48, 1.5), "packet_loss_pct": (0.1, 0.08)}

# name -> (what is injected, the platform signal names we expect, whether they must share one incident)
SCENARIOS = {
    "cpu-spike": ({"cpu_pct": 97.0}, {"cpu"}, False),
    "baseline-deviation": ({"cpu_pct": 70.0}, {"cpu"}, False),  # below every threshold: only a deviation from baseline can flag it
    "latency-spike": ({"latency_ms": 600.0}, {"latency"}, False),
    "packet-loss": ({"packet_loss_pct": 25.0}, {"packet_loss"}, False),
    "disk-fill": ({"disk_pct": 97.0}, {"disk"}, False),
    "failed-logins": ("burst", {"failed_login"}, False),
    "alert-storm": ({"cpu_pct": 97.0, "latency_ms": 600.0, "packet_loss_pct": 25.0, "mem_pct": 97.0}, {"cpu", "latency", "packet_loss", "memory"}, True),
}


# ---------------------------------------------------------------- pure evaluation (unit tested)
def epoch_of(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def evaluate(name: str, expected: set[str], grouped: bool, source: str, incidents: list[dict], t_inject: float) -> dict:
    """Judge one scenario from the platform's incidents."""
    mine = [i for i in incidents if i["source_id"] == source]
    signals = [s for i in mine for s in i.get("signals", [])]
    after = [s for s in signals if epoch_of(s["event_ts_utc"]) >= t_inject - 1]
    before = [s for s in signals if epoch_of(s["event_ts_utc"]) < t_inject - 1]
    seen = {s["signal"] for s in after}
    missed, extra = sorted(expected - seen), sorted(seen - expected)
    delays = {}
    for s in after:
        if s["signal"] in expected:
            delays[s["signal"]] = min(delays.get(s["signal"], 1e9), epoch_of(s["alert_ts_utc"]) - t_inject)
    first = round(min(delays.values()), 1) if delays else None
    last = round(max(delays.values()), 1) if len(delays) == len(expected) else None
    incident_ids = {i["id"] for i in mine if any(s in after for s in i.get("signals", []))}
    ok = not missed and not extra and last is not None and last <= ALERT_TARGET_S and (len(incident_ids) == 1 if grouped else True) and not before
    return {
        "scenario": name, "expected": sorted(expected), "actual": sorted(seen), "missed": missed, "extra": extra,
        "false_alarms_before_injection": len(before), "first_alert_s": first, "all_expected_alerts_s": last,
        "incidents": len(incident_ids), "alerts_in_those_incidents": sum(i["alert_count"] for i in mine if i["id"] in incident_ids),
        "methods": sorted({s.get("method", "") for s in after if s["signal"] in expected}), "verdict": "PASS" if ok else "FAIL",
    }


def false_alarms(decoy_sources: list[str], incidents: list[dict]) -> dict:
    mine = [i for i in incidents if i["source_id"] in decoy_sources]
    return {"incidents": len(mine), "alerts": sum(len(i.get("signals", [])) for i in mine),
            "signals": sorted({s["signal"] for i in mine for s in i.get("signals", [])})}


# ---------------------------------------------------------------- driving the stream
def lines_for(host: str, rng: random.Random, overrides: dict | None = None) -> list[str]:
    ts = sc.iso(time.time())
    out = []
    for metric, (mean, spread) in BASELINE.items():
        value = rng.gauss(mean, spread)  # always drawn, so an override never shifts the random sequence
        value = (overrides or {}).get(metric, value)
        out.append(f"ts={ts} host={host} metric={metric} value={round(max(0.0, value), 2)}")
    out.append(f"ts={ts} host={host} metric=service_up value=1")
    return out


def run(warmup: float, inject: float, recover: float, seed: int) -> dict:
    tag = format(random.Random(seed).getrandbits(24), "06x") if seed is not None else "000000"
    rng = random.Random(seed)
    decoys = [f"normal-{tag}-{i}" for i in (1, 2)]
    hosts = {name: f"{name}-{tag}" for name in SCENARIOS}
    timing = sc._call(f"{sc.COLLECTOR}/local/timing")[1]
    window_s = (timing or {}).get("window_s", 5)
    print("EXPECTED (written before anything is sent):")
    for n, (_, exp, grp) in SCENARIOS.items():
        print(f"  {n:20} on {hosts[n]}: signals {sorted(exp)}" + (", all in ONE incident" if grp else "") + f", first alert within {ALERT_TARGET_S:.0f} s")
    print(f"  {'normal period':20} on {', '.join(decoys)}: no alert at all\n")

    start = time.time()
    t_inject = start + warmup
    end = t_inject + inject + recover
    sent_burst = False
    print(f"streaming {len(hosts) + len(decoys)} hosts: {warmup:.0f} s normal, {inject:.0f} s injection, {recover:.0f} s normal ...")
    while time.time() < end:
        now = time.time()
        injecting = t_inject <= now < t_inject + inject
        batch = []
        for d in decoys:
            batch += lines_for(d, rng)
        for name, host in hosts.items():
            spec = SCENARIOS[name][0]
            over = spec if (injecting and isinstance(spec, dict)) else None
            batch += lines_for(host, rng, over)
        if injecting and not sent_burst:
            sent_burst = True
            ts = sc.iso(time.time())
            batch += [f'ts={ts} host={hosts["failed-logins"]} msg="Failed password for root from 203.0.113.{i % 250 + 1} port 22"' for i in range(30)]
        sc.collector_send(batch)
        time.sleep(max(0.0, 1.0 - (time.time() - now)))
    print("draining: waiting for the last windows to be processed ...")
    time.sleep(window_s + 8)

    from collector.config import Config
    pseudo_secret = Config(data_dir=":memory:").pseudo_secret
    source = {n: pseudonym(h, pseudo_secret) for n, h in hosts.items()}
    decoy_sources = [pseudonym(d, pseudo_secret) for d in decoys]
    incidents = sc.saas_get("/v1/incidents")
    if not isinstance(incidents, list):
        raise RuntimeError(f"cannot read incidents: {incidents}")
    egress = sc._call(f"{sc.COLLECTOR}/local/egress?limit=5000")[1]
    seen_sources = {e["payload"]["source_id"] for e in egress}
    if not (set(source.values()) | set(decoy_sources)) <= seen_sources:
        raise RuntimeError("could not map the test hosts to source IDs (is this collector using a non-default pseudonym secret?)")

    results = [evaluate(n, SCENARIOS[n][1], SCENARIOS[n][2], source[n], incidents, t_inject) for n in SCENARIOS]
    fa = false_alarms(decoy_sources, incidents)
    pre = sum(r["false_alarms_before_injection"] for r in results)
    normal_windows = int((len(decoys) * (end - start) + len(hosts) * warmup) / window_s) * len(BASELINE)
    return {
        "started_utc": sc.iso(start), "window_s": window_s, "profile": (timing or {}).get("profile"), "seed": seed,
        "durations_s": {"warmup": warmup, "inject": inject, "recover": recover},
        "hosts": {"decoys": decoys, "scenarios": hosts}, "results": results,
        "false_alarms": {"on_decoy_hosts": fa, "on_scenario_hosts_before_injection": pre, "total_alerts": fa["alerts"] + pre,
                         "normal_metric_windows_observed": normal_windows},
        "missed": sum(len(r["missed"]) for r in results), "extra": sum(len(r["extra"]) for r in results),
        "verdict": "PASS" if all(r["verdict"] == "PASS" for r in results) and fa["alerts"] + pre == 0 else "FAIL",
    }


def render(res: dict) -> str:
    fa = res["false_alarms"]
    out = [f"# Scenario check {res['started_utc']}", "",
           f"Collector profile `{res['profile']}`, window {res['window_s']} s, seed {res['seed']}. {res['durations_s']['warmup']:.0f} s normal, "
           f"{res['durations_s']['inject']:.0f} s injection, {res['durations_s']['recover']:.0f} s normal again, all scenarios in parallel on separate hosts. "
           f"Overall: **{res['verdict']}**", "",
           "| Scenario | Expected | Actual | Missed | Extra | First alert | All expected | Incidents (alerts) | Method | Verdict |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["results"]:
        out.append(f"| {r['scenario']} | {', '.join(r['expected'])} | {', '.join(r['actual']) or 'none'} | {', '.join(r['missed']) or '-'} | {', '.join(r['extra']) or '-'} | "
                   f"{r['first_alert_s']} s | {r['all_expected_alerts_s']} s | {r['incidents']} ({r['alerts_in_those_incidents']}) | {', '.join(r['methods'])} | **{r['verdict']}** |")
    out += ["", "## False and missed alerts", "",
            f"- False alarms on the {len(res['hosts']['decoys'])} normal hosts: {fa['on_decoy_hosts']['alerts']} alert(s) in {fa['on_decoy_hosts']['incidents']} incident(s) {fa['on_decoy_hosts']['signals'] or ''}",
            f"- False alarms on scenario hosts before their injection: {fa['on_scenario_hosts_before_injection']}",
            f"- Denominator: about {fa['normal_metric_windows_observed']} normal metric-windows observed (hosts x metrics x windows)",
            f"- Missed expected signals: {res['missed']}; extra signals after injection: {res['extra']}", "",
            "## Definitions and limits", "",
            "- False alarm: an alert on a normal host at any time, or on a scenario host before its injection. Missed: an expected signal that never appeared. Extra: a signal after injection that was not expected.",
            "- Grouped: alerts of one source in the same incident. Grouping is noise reduction, not a false-alarm rate.",
            "- One short run with a small denominator, on the simulator. A quiet run is not a general false-alarm rate, and these are not the organizer's scenarios.",
            "- Recovery (health returning to normal) is not judged. The platform's detectors are rules and statistics; an alert is a lead to investigate, not a proven cause."]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warmup", type=float, default=60)
    ap.add_argument("--inject", type=float, default=20)
    ap.add_argument("--recover", type=float, default=20)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    try:
        res = run(a.warmup, a.inject, a.recover, a.seed)
    except RuntimeError as exc:
        print(f"cannot run: {exc}")
        return 2
    text = render(res)
    print("\n" + text)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (EVIDENCE / f"scenarios-{stamp}.md").write_text(text, encoding="utf-8")
    (EVIDENCE / f"scenarios-{stamp}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"\nRESULT: {res['verdict']}   (evidence: docs/p3/evidence/scenarios-{stamp}.md)")
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
