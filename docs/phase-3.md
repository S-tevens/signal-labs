# Phase 3: Implementation and working prototype (35 marks): status and work split

Status of `main` at `8126f6f`. **Verified** means Member 1 ran it live, or in the tests, on one Windows machine. **Built** means it exists but has not been checked by Member 1. **Estimate** means worked out from the settings in the code, not measured. Nothing here is a production claim.

Same two people as before: **Member 1 (Edge)** owns the collector, the scripts and everything that runs, drives and measures the system; **Member 2 (Platform)** owns the SaaS and the dashboard. Member 2 is currently building the **data flow tab** (task P15 below). Put your names in section 4.

## 1. What the judges will look for

Phase 3 is the biggest block: 35 marks, **10 of them for real-time performance and delivery reliability**. The guide says everything is judged live, from the shared organizer stream, and that numbers must be **measured, not claimed**.

Evidence the guide says judges will ask for:

1. A live side-by-side: a raw log with a secret on the collector, and the redacted metadata on the SaaS dashboard.
2. Timestamps proving the real-time targets, measured from the shared stream.
3. A forced SaaS outage, then reconnection, with sent and received IDs compared.
4. The egress proof panel's log for a specific payload.

**Strong:** everything demonstrated live from the shared stream, the egress log matches what the SaaS received, reliability numbers measured. **Weak:** polished screens backed by hard-coded data, no proof of what leaves the collector, no behaviour under failure. Three items are mandatory for every team: real-time targets measured from timestamps, the same organizer stream, and an egress proof panel.

## 2. The Phase 3 sheet against the repo

| Sheet item | Status | Evidence | Gap |
|---|---|---|---|
| **Working collector on the organizer stream; raw data and secrets stay local** | Partial | The collector runs on the simulator and on real host telemetry; the egress panel and the `secret` scenario show raw staying local | **The organizer stream is not integrated** and its format is unknown. There is no canary-style proof that nothing raw reaches the platform, and nothing to show it on someone else's data |
| **SaaS shows only allow-listed metadata, per tenant** | Mostly | Strict schema plus frozen-contract validation; row-level security tested on Postgres | A second tenant has never run live; no scan proving no raw value reached any platform table or API |
| **Dashboard with four health states, thresholds, stale-data handling** | Built, partly checked | States and a "Telemetry stale" reason were seen live; Health history renders; thresholds live in `saas/config/thresholds.yaml` | Thresholds are not shown in the UI; stale handling not checked in a browser; the collector's heartbeat sends a constant config hash and **no resource usage**, though the guide asks the fleet view to show both |
| **Contextual anomaly alerts; outage detection, buffering, retry** | Verified live | Explained incidents with lineage; alerts measured at 3.6 to 6.6 s; an outage buffered 42 to 70 payloads and lost none; retry with backoff; replica kill lost none | **Offline detection measured at 60.2 s from the last heartbeat, 0.2 s over the target**, because the platform's threshold is exactly 60 s (P17) |
| **Egress proof panel shows the exact payload before it leaves** | Partial | `/local/ui` shows raw beside the exact payload with a leak check | Payloads leave within about a second, so a judge cannot catch one **before** it leaves; the panel cannot show that the SaaS received the same bytes |
| **Real-time: dashboard ≤ 10 s, alert ≤ 15 s, offline ≤ 60 s, zero loss and duplicates** | **Measured**: 3 of 4 pass | With the `realtime` collector profile: dashboard 5.95 s, alert 3.6 s (hard threshold) and 6.6 s (baseline deviation), zero loss and zero duplicates. At the default timing the dashboard figure is 10.2 to 11.1 s (FAIL) | **Offline fails by 0.2 s** until the platform threshold is lowered (P17). Results are one run each on one machine ([summary](p3/evidence/SUMMARY.md)) |

## 3. Do the settings meet the timing targets? Measured

Measured with `scripts\measure.ps1` (E14); every run and its settings are in [p3/evidence/SUMMARY.md](p3/evidence/SUMMARY.md). An earlier version of this section gave estimates from the code; the table shows how they held up.

| Target | At the default timing (5 s window, 2 s grace) | With `PROFILE=realtime` (2 s window, 1 s grace) | Earlier estimate |
|---|---|---|---|
| **Collection → dashboard ≤ 10 s, p95** (strict: clock starts at the window's start) | **10.2 s and 11.1 s: FAIL** | **5.95 s: PASS** | 8 to 11 s: **right** |
| **Breach → alert ≤ 15 s** | 4.4 s: PASS (hard threshold) | 3.6 s PASS (hard threshold), 6.6 s PASS (deviation from baseline) | 10 to 14 s: **wrong**, because a hard threshold breach is alerted without waiting for the persistence rule |
| **Offline ≤ 60 s** (from the last heartbeat) | **60.16 s: FAIL** | **60.28 s: FAIL** | 60 to 61 s: **right** |
| **Zero loss and duplicates** | 74 created, 0 missing, 0 duplicates, replay 5.5 s | 136 created, 0 missing, 0 duplicates, replay 5.8 s | low risk: **right** |

What follows:

- **Dashboard latency** has a floor of window + grace before any delivery delay. The `realtime` profile cuts that floor from 7 s to 3 s and passes with about 4 s of margin. The cost is roughly 2.5 times more payloads per collector. The runner `scripts\run-local.ps1` now uses this profile by default.
- **Offline** is a platform setting. The platform marks a collector Poor exactly 60 s after its last heartbeat, and the result is always about 0.2 to 0.3 s later. Lowering `offline_after_s` to about 40 s (with the 5 s heartbeat) should give about 40 s. That is task P17.
- **Burst detection note.** The failed-login burst threshold is per window, so a 2 s window makes the effective rate threshold 2.5 per second instead of 1 per second. Large bursts (the scenario the sheet describes) are unaffected.
- **Open question for the platform:** the dashboard path waited for the next pushed snapshot (about every 2 s); the measured fetch afterwards took about 0.4 s. A push on arrival (P18) would shave the rest.

## 4. Work split for two people

Ownership is unchanged from `docs/phase-2.md`: Member 1 owns `collector/**`, `simulator/**`, `scripts/**` and `docs/p3/collector.md`; Member 2 owns `saas/**`, `dashboard/**`, `.github/**` and `docs/p3/platform.md`. New files wherever possible, branches `edge/<topic>` and `platform/<topic>`, merge at least every two hours.

| | Member 1: Edge | Member 2: Platform |
|---|---|---|
| **Name** | _______ | _______ |

Priority: **P0** = a Phase 3 tick or a mandatory item; **P1** = strengthens Phase 4 or a bonus; **P2** = if time remains.

### Member 1: Edge (collector, measuring, proving, rehearsing)

| ID | P | Task | Files | Done when |
|---|---|---|---|---|
| E14 | P0 | **Measurement harness.** One command measures the three timings and delivery from timestamps, on live traffic (never backdated): collection to dashboard (first sight of each payload by a dashboard-style client, reported as p50, p95 and p99, from the newest record **and** from the window start), breach to alert (inject a spike, time to the incident), offline detection (kill a collector, time to Poor), and sent vs received ID sets across a forced outage. Each result is PASS or FAIL against its target and the raw timestamps are saved as an evidence file | `simulator/measure.py`, `scripts/measure.ps1`, `docs/p3/evidence/` | One command prints a table of measured values against 10 s, 15 s and 60 s, plus the ID reconciliation, and writes the evidence file |
| E15 | P0 | **Timing profile.** A `PROFILE=realtime` preset for the collector timing settings (section 3), measured against the defaults with E14, with the trade-off written down. Agree the platform-side numbers with Member 2 (P17, P19) | `collector/config.py`, `scripts/run-local.ps1` | Measured p95 collection to dashboard ≤ 10 s and alert ≤ 15 s with at least 3 s of margin, or the gap and its cause documented |
| E16 | P0 | **Organizer-stream readiness.** Input adapters beyond `POST /ingest` (UDP syslog, TCP lines, follow a file), CSV and NDJSON parsers, and a mapping file (`collector/mapping.yaml`) for metric name aliases, unit conversions, timestamp formats and host field names, so a new stream format needs configuration, not code | `collector/adapters/`, `parsers/`, `mapping.yaml` | Five differently shaped sample streams all produce valid payloads; unknown fields are dropped; tests |
| E17 | P0 | **Replay and scripted timeline.** Replay a recorded stream at real or faster speed with timestamps rebased to now, and run a scripted timeline that mimics the organizers' injections: steady, CPU spike, latency spike, failed-login burst, SaaS outage | `simulator/replay.py`, `simulator/timelines/` | A five-minute timeline replays identically every run and is what E14 and the rehearsal use |
| E18 | P0 | **Hold and release in the egress panel.** A local-only Hold button stops sending so pending payloads sit in the outbox and the panel shows exactly what is about to leave; Release resumes. Add a buffer strip (link state, pending count, next retry, last error), a SHA-256 of each payload's exact bytes, and sent time per payload. Hold times out after 5 minutes so it cannot be forgotten | `collector/ui/`, `main.py`, `sender.py` | With Hold on, a record containing a secret appears as a pending payload with no secret in it; after Release the same ID and digest reach the SaaS |
| E19 | P0 | **Proof tools: match and canary scan.** *Match:* compare the last N sent payloads field by field with the platform's stored observations and report any difference. *Canary scan:* plant unique canary strings in secret, email, IP, host and username positions, then search every platform API response and the platform's database tables for them, and confirm they exist in the collector's raw store | `simulator/verify.py`, `scripts/verify.ps1` | One command prints PASS or FAIL for "the egress log matches what the SaaS received" and for "no canary reached the platform" |
| E20 | P1 | **Tenant isolation and allow-list demo.** Add a second tenant (`t-globex`) to the dev auth config; a scenario enrolls a collector for each tenant, shows each dashboard token sees only its own fleet, metrics and incidents, a payload naming the other tenant is refused, a cross-tenant object fetch returns 404, and deliberately bad payloads (extra field, secret-like summary, unknown metric, non-UTC time) are each rejected with a reason | `scripts/run-local.ps1`, `simulator/scenarios.py` | The scenario prints PASS for each isolation and allow-list check |
| E21 | P1 | **Collector heartbeat that means something.** Send the collector process's own CPU and memory, its uptime and a real hash of its effective configuration (not the constant `dev`), so the fleet view can show resource usage and configuration status as the guide asks | `collector/sender.py` | The fleet shows non-empty resource usage and a config hash that changes when a setting changes |
| E22 | P1 | **Rehearsal runner.** One script runs every scenario plus the measurements in the order a judge would see them, pauses between steps, and writes a pass/fail table with timestamps; a second script opens the collector panel and the dashboard side by side | `scripts/rehearse.ps1`, `scripts/open-demo.ps1` | A full run completes and leaves an evidence file for the rehearsal |
| E23 | P1 | **Real-time collector health verdict.** Replace the constant "Good" with a local verdict (using the same thresholds as the platform) so the collector's own report agrees with the platform | `collector/pipeline.py` | A CPU spike changes the `health_state` the collector sends |
| E24 | P2 | **Pipeline stage page** (carried over from E6): received, parsed by format, redacted by rule, dropped, aggregated, queued, sent | `collector/ui/`, `main.py` | Counts per stage add up and are visible live |
| E25 | P0 | Docs: `docs/p3/collector.md` (demo order, expected output of each command, how each target is measured) and the evidence files; update the statuses in this file | `docs/p3/` | A teammate can run the whole Phase 3 demo from the document alone |

**Progress (Member 1):** E18 done (hold and release, buffer strip, digest, sent time, 5-minute auto-release, `demo.ps1 hold`, 7 unit tests); E19 done (`simulator/verify.py`, `scripts/verify.ps1`: match and canary scan with positive controls, 12 unit tests, first evidence in `docs/p3/evidence/verify-*.md`); E14 done (`simulator/measure.py`, `scripts/measure.ps1`, evidence in `docs/p3/evidence/`, 14 unit tests); E15 done (`PROFILE=realtime`, `run-local.ps1 -Profile`, measured, 7 unit tests). E16 done (`collector/mapping.py` + `mapping.yaml`, UDP/TCP/file-follow adapters, CSV and multi-metric rows, five sample streams, tests); E17 done (`simulator/replay.py`, `timelines/demo.json`, deterministic builds, tests). E20 done (`t-globex` in the dev auth, `demo.ps1 tenants`, 13 checks); E21 done (real resource usage and config hash in the heartbeat, 4 tests; uptime omitted because the platform heartbeat contract has no field for it). E22 done (`scripts/rehearse.ps1`, `open-demo.ps1`, evidence in `docs/p3/evidence/rehearsal-*.md`); E23 done (`collector/health.py`: the collector's `health_state` follows the platform's thresholds, with a drift test; this exposed that the platform did not map `service_up` and `connectivity_up` to its availability and connectivity thresholds, so a downed service counted as Excellent: two aliases added in `saas/aiops.py`, to tell Member 2). (Phase 4 E27 done: `scripts/trace.ps1`.) E24 done (`/local/stages` and a live Pipeline stages box in the panel: received by format, redacted by rule, dropped, aggregated, queued, outbox; two balance checks; 4 tests); E25 done ([p3/collector.md](p3/collector.md): demo order, expected output, how each target is measured). All Member 1 Phase 3 tasks (E14 to E25) are done.

### Member 2: Platform (dashboard, health, timing path, proof views)

| ID | P | Task | Files | Done when |
|---|---|---|---|---|
| P15 | P0 | **Data flow tab** (in progress). Live view of collector → proxy → replicas → database with real counts and statuses, not fixtures | `dashboard/src/` | Every number on the tab comes from a live endpoint; killing a replica is visible |
| P16 | P0 | **Health states in the dashboard.** The four states with their thresholds visible (read from the platform's configuration), a reason for each state, stale data shown as age and downgraded, state history | `dashboard/src/`, `saas/main.py` | A judge can see why a collector is Fair or Poor and what threshold caused it |
| P17 | P0 | **Offline and stale thresholds.** Set `offline_after_s` below 60 (about 40) and a Fair threshold for staleness, matched to the heartbeat interval; test it | `saas/config/thresholds.yaml`, tests | Poor appears within 60 s of the last heartbeat with at least 10 s of margin, measured by E14 |
| P18 | P0 | **Dashboard freshness path.** Push updates when data arrives instead of a fixed 2 s snapshot, keep render acknowledgements, show the measured p95 with sample count and window, and show "last updated" | `saas/main.py`, `dashboard/src/api.js` | Measured collection to dashboard p95 ≤ 10 s (with E14) |
| P19 | P0 | **Alert timing.** Choose the persistence setting together with the collector window (E15) so an alert appears within 15 s with margin, and show raised-at against event time | `saas/ingest.py`, `thresholds.yaml` | Measured breach to alert ≤ 15 s with at least 3 s of margin |
| P20 | P0 | **"What the SaaS received" view.** For a payload ID, show the stored fields exactly as the platform holds them (allow-listed, per tenant), reachable by link, so it can sit beside the collector's panel | `dashboard/src/` | A payload ID from the collector panel opens the matching stored record |
| P21 | P1 | **Tenant isolation in the UI.** Show the tenant name, switch only by token, and show nothing from another tenant (uses E20's second tenant) | `dashboard/src/` | Two tokens show two disjoint fleets |
| P22 | P1 | **Second region live and a scale figure** (carried over from P7 and P8): a second region running with its own database, and a recorded throughput number with its bottleneck named | `saas/`, `docs/p3/platform.md` | A region-bound tenant works in a second region; a figure is in the docs |
| P23 | P1 | **Browser check of the earlier screens** (P9 to P12): incident workspace, action buttons, lineage, live updates; fix what is wrong | `dashboard/src/` | Each screen verified with live data |
| P24 | P0 | Docs: `docs/p3/platform.md` with the platform's evidence and any thresholds changed | `docs/p3/` | Matches what runs |

## 5. Seams (where the two halves meet)

| Seam | Rule |
|---|---|
| **Timing settings** | Collector window, grace and intervals (E15) and platform persistence, offline and stream settings (P17, P18, P19) are one budget. Agree the numbers together, change them in one pull request each, and re-measure with E14 afterwards |
| **Evidence tools read the platform's public API** | E14 and E19 use the existing endpoints (`/v1/fleet`, `/v1/metrics`, `/v1/incidents`, `/v1/proof`, `/v1/objects/...`). Member 2 tells Member 1 before changing any of their shapes |
| **Test tenants and credentials** | Member 1 adds `t-globex` and its tokens to the dev auth config in `scripts/run-local.ps1`; Member 2 provides anything the platform needs for a second tenant |
| **Payload contract** | Unchanged. A payload digest (E18) is computed over the existing bytes and adds no field |
| **Organizer stream** | Member 1 owns the adapters and mapping (E16); Member 2 only needs to be told if new metric names appear |

**Order of work.** Member 1 starts with E14, so everything can be measured, then E16 and E17 (so the collector is ready whatever the stream looks like), then E18 and E19. E15 comes after the first baseline measurement. Member 2 starts with P15 (already in progress) and P16, then P17 to P19 after E14's baseline, then P20. Then the P1 items. Freeze features with enough time left to rehearse (E22).

## 6. Questions to ask the organizers now

1. How is the stream delivered: a file, an HTTP feed, syslog, a message queue? Is it pushed to us or do we pull it?
2. What does a record look like? Which field is the event timestamp, in what format and timezone?
3. Which metric names and units appear (and does CPU arrive as a percentage or a fraction)?
4. How many hosts or sources, and at what rate?
5. How are bursts, latency spikes and outages injected, and can we see a recording to rehearse on?
6. How will the real-time targets be measured: from which clock, and which timestamp counts as "event time"?
7. How are the "raw log with a secret" and "repeated failed logins" scenarios represented in the stream?

## 7. Done checklist for Phase 3 (tick from the running system)

- [ ] Collector running on the organizer stream, with raw data and secrets staying local (E16, E17, E19) **Open:** only the simulator has been used; waiting for the organizer's stream format (E26).
- [x] Platform shows only allow-listed metadata, per tenant, with the proof (E19, E20, P20, P21)
- [ ] Dashboard shows the four health states, their thresholds and stale-data handling (P16, P17) **Open:** Member 2 to confirm in the browser (thresholds and the offline setting are in place).
- [x] Contextual anomaly alerts; outage detection, buffering and retry shown live (E14, P19)
- [x] Egress proof panel shows the exact payload before it leaves, and it matches what the SaaS received (E18, E19, P20)
- [x] Measured: dashboard ≤ 10 s (pass at `realtime`), alert ≤ 15 s (pass), zero loss and duplicates (pass), with evidence files; offline ≤ 60 s now passes at 40.26 s with `offline_after_s: 40` (latest run, 2026-11-20 18:30 UTC) (E14, E15, P17 to P19); final rehearsal 2026-11-20 19:31 UTC: dashboard 7.00 s (n=93), alerts 2.95 s and 6.43 s, offline 40.17 s, 137 created and 0 missing or duplicated
- [ ] Mandatory: real-time measured from timestamps; the shared organizer stream; the egress proof panel **Open:** two of three done (real-time measured, egress proof panel); the shared organizer stream is not connected yet.
- [x] One full rehearsal run recorded (E22) Recorded: [rehearsal-20261120T192509Z.md](p3/evidence/rehearsal-20261120T192509Z.md), 15 steps, no failures.

## 8. Risks

- **The organizer stream arrives late or in an unexpected shape.** Mitigation: adapters and a mapping file (E16), and rehearsing on a recorded timeline (E17).
- **The targets are missed at the default timing.** Confirmed by measurement for the dashboard and offline targets; mitigated for the dashboard by the `realtime` profile, and for offline only by P17. Repeat the measurements before the final, since each figure is a single run.
- **Tuning for speed costs volume.** A shorter window sends more payloads; the retention caps bound the disk, and the volume should be measured with E15.
- **A polished screen with fixed data.** The dashboard's Egress screen is synthetic by design (raw records must never go through the central platform). Label it clearly and demonstrate the real collector panel, with the platform's "what was received" view (P20) beside it.
- **Clock differences.** All measurements here run on one machine, so one clock. If the organizers measure across machines, agree on a time source first.
