# Phase 3 collector: demo guide

Everything the collector side (Member 1) built for Phase 3, in the order to demonstrate it, with what you should see. A teammate can run the whole demo from this page. Commands are PowerShell, run from the repository root. Setup details are in [../../scripts/README.md](../../scripts/README.md).

## 0. Start

```
.\scripts\run-local.ps1 -Tls          # Postgres, two SaaS replicas, failover proxy, collector, simulator, dashboard
.\scripts\open-demo.ps1               # egress panel (left) and dashboard (right)
```

Leave the simulator on: the platform needs about 8 windows of history per metric before it scores deviations from baseline. Everything runs on development credentials and a private CA.

- Egress panel: `http://127.0.0.1:8101/local/ui` (this machine only). Dashboard: `http://127.0.0.1:5173`. Platform entry point: `https://127.0.0.1:8080`.
- Collector timing is the `realtime` profile (2 s window, 1 s grace, 0.25 s send interval, 5 s heartbeat), the one that measured under the dashboard target. `-Profile default` gives the original 5 s window.

To run all of the below in order and get a pass/fail table: `.\scripts\rehearse.ps1` (about 8 minutes). The table and every step's output go to `docs\p3\evidence\rehearsal-<time>.md`.

## 1. Privacy: what leaves and what does not

| Step | Command | What you should see |
|---|---|---|
| Secrets stay local | `.\scripts\demo.ps1 secret` | Six lines `... leaked into egress? False` and `RESULT: PASS`. In the panel the raw records show the secrets highlighted; the payload that left has counts and template summaries only |
| Look before it leaves | `.\scripts\demo.ps1 hold` | HOLD, the new payload(s) shown `pending` with a SHA-256 and no secret, none of them at the SaaS, then RELEASE, the same IDs arrive with an unchanged digest. Ends `RESULT: PASS` |
| Panel by hand | click **Hold sending** in the panel, send a record, pick it, click **Release** | The strip shows `HELD, auto-release in N s`; a held payload shows its digest and "Not sent yet"; after release it shows the sent time. A hold ends by itself after 5 minutes |
| Pipeline stages | the "Pipeline stages" box at the top of the panel (or `GET /local/stages`) | Received (by format), redacted (by rule), dropped, aggregated, queued, in the outbox. Two checks show a tick when the counts add up |
| Trace one payload | `.\scripts	race.ps1 --demo` (or `--latest`, or a payload ID picked in the panel) | Four hops, each PASS or FAIL: the raw records (secrets masked), the exact outgoing payload with its SHA-256 and a leak check, the platform's stored observation compared field by field, and the incident with its signal and recommendation. Evidence in `docs\p3\evidence	race-*.md` |
| Proof tools | `.\scripts\verify.ps1` | `MATCH: PASS` (the collector's egress log equals what the platform stored, field by field) and `CANARY: PASS` (eight planted fake secrets found nowhere on the platform: egress log, API, every database table for all tenants, logs), then `OVERALL: PASS`. Exit code 0. If the database cannot be read the result is INCOMPLETE, never PASS |
| Tenant isolation | `.\scripts\demo.ps1 tenants` | 13 lines `PASS` (disjoint fleets, observations and metrics, 404 on cross-tenant fetch, cross-tenant payload refused, bad payloads each rejected with a reason), then `RESULT: PASS (13 of 13 checks)` |

## 2. Live incidents the judges inject

Each prints what to expect, waits for windows to close and shows the platform's incidents. Scenarios on the same host within 2 minutes join one incident (correlation is per source and 120 s); wait between them or accept the grouping.

```
.\scripts\demo.ps1 failed-logins   # 30 raw login lines become one critical burst event; no raw line leaves
.\scripts\demo.ps1 cpu-spike       # CPU on web-1 flagged, with signal, baseline and a recommendation
.\scripts\demo.ps1 latency         # latency on router-1
.\scripts\demo.ps1 packet-loss
.\scripts\demo.ps1 disk
.\scripts\demo.ps1 alert-storm     # many alerts collapse into few incidents (noise reduction)
.\scripts\demo.ps1 remediation     # propose, approve, roll back, audit trail; simulated, nothing is executed
```

The collector's own `health_state` on each payload follows the platform's thresholds (`collector/health.yaml`, with a test that fails if the two drift): a 97% CPU payload is `Poor`, a 35% one `Excellent`.

Rehearse them with expected versus actual results: `.\scripts\scenario-check.ps1` (about 2.5 minutes). It writes the expected result first, runs a normal baseline on decoy hosts and seven scenarios in parallel on separate hosts (CPU spike, baseline deviation at 70% CPU, latency, packet loss, disk fill, failed logins, alert storm), then counts missed, extra and false alerts with the window and denominator stated. Latest run: 7 of 7 PASS, first alerts 2.4 to 6.4 s, the alert storm grouped 40 alerts into 1 incident, 0 false alarms over about 1,860 normal metric-windows (small and simulated, so not a general false-alarm rate). Evidence: `docs\p3\evidence\scenarios-*.md`.

## 3. Reliability

```
.\scripts\demo.ps1 outage     # cut the collector's link, buffer, reconnect; compares sent and received ID sets
.\scripts\demo.ps1 delivery   # duplicate, out-of-order and same-ID-different-body sent to the platform
.\scripts\demo.ps1 flood      # 40,000 lines, an oversize line and a 3 MiB request against tight caps
.\scripts\demo.ps1 failover   # a replica dies; the proxy fails over and nothing is lost
```

Expected: `outage` ends with zero missing and zero duplicates; `delivery` shows the duplicate absorbed, the late event placed by event time and the conflict surfaced; `flood` shows the caps holding with losses counted and reported as an event.

## 4. Bringing in the organizers' stream

Formats: NDJSON, key=value, RFC3164 syslog, CSV with a header, plain text. Extra inputs (off by default, bind to this machine): `UDP_SYSLOG_PORT`, `TCP_LINES_PORT`, `FOLLOW_FILES`. A new field naming, unit or time format is handled in `collector/mapping.yaml`, not code. Unknown fields are dropped before the pipeline.

```
python simulator\samples.py --list                                        # five differently shaped sample streams
python simulator\replay.py play simulator\timelines\demo.json --speed 5   # scripted 5-minute timeline
```

The timeline is steady traffic, a CPU spike at 90 s, a latency spike at 150 s, a failed-login burst at 190 s and an outage from 230 s to 255 s. It builds identically every time and its timestamps are always rebased to now. If the organizers' format is not covered, send us two sample lines and add the aliases to the mapping.

## 5. How each target is measured

`.\scripts\measure.ps1` (about 6 minutes; run it with `run-local.ps1 -Tls -NoSimulator` for the cleanest numbers). Every test uses live timestamps on a unique host, so it cannot be confused with other traffic. Each result is PASS or FAIL against its target, and the raw timestamps are saved in `docs\p3\evidence\measure-<time>.json`.

| Target | Measured as | Latest result |
|---|---|---|
| Collection to dashboard, p95 at most 10 s | Clock starts at the earliest record the window could hold (the strict reading). The dashboard path does what the real dashboard does when a snapshot arrives: fetch fleet, incidents, proof and four metric series | 6.13 s (n=90) on `realtime` (latest run); 10 to 11 s on `default` |
| Alert at most 15 s | Inject a spike on a unique host, time to the incident: 99% CPU (hard threshold) and 70% CPU (deviation from baseline) | 5.7 s and 6.2 s (latest run) |
| Offline at most 60 s | Kill the collector, time from its **last heartbeat** to state Poor | 40.26 s with `offline_after_s: 40` (it was 60.2 s, a 0.2 s miss, at the old 60 s setting) |
| Zero loss and duplicates | Force an outage, compare the collector's created IDs with the platform's stored IDs, and check for repeated IDs independently (the platform's own duplicate counter is a constant 0) | 133 created, 0 missing, 0 duplicates, replay in about 5.5 s |

All of it is on one machine and one clock. Full runs and caveats: [evidence/SUMMARY.md](evidence/SUMMARY.md). The rehearsal and proof runs sit next to it as `rehearsal-*.md` and `verify-*.md`.

## 6. Honest limits

- Measurements are one run per row on one machine; margins under a second are noise.
- The canary scan proves these canaries did not travel, not that no other secret ever could. Redaction is rule-based and can miss a secret in a format it does not know; free text never travels in payloads regardless.
- The heartbeat reports the collector process's CPU, memory and disk share and a config hash, but not uptime (the platform contract has no field for it).
- The input adapters are unauthenticated; use them on a trusted network.
- Hold only controls this collector's own outbox. It is a local, human-in-the-loop view, not an access control.
- The platform is a single-machine development setup (two replicas behind a small failover proxy, one Postgres).
