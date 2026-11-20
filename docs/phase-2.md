# Phase 2 — Architecture & Technical Design: status, Foundry-inspired design, and work split

Status of `main` after `platform/phase2` and `edge/retention-enrollment` were merged. **Verified** means Member 1 ran it live, or in the tests, on one Windows machine. **Built** means it exists but Member 1 did not check it. Nothing here is a production claim.

**Where things stand.** Every item on the Phase 2 sheet has a working implementation. From Member 1: TLS, real host telemetry, aggregation and local analysis, the data policy, the real egress panel, retention and limits, enrollment and the failover proxy. From Member 2: the ontology, lineage, simulated actions, contract enforcement, anomaly persistence and region-bound databases. The suite passes (137 tests, including the database tests) and GitHub Actions is green. What is missing is evidence, not features: no measured scale figure, no second region shown live, and the real-time targets have not been measured cleanly.

Two people share the work: **Member 1 (Edge)** owns everything inside the customer environment and the way the system is run and demonstrated; **Member 2 (Platform)** owns the central SaaS and everything the judges see on the dashboard. Put your names next to these in section 4.

Judges tick only what is demonstrated live, and Phase 2 is 25 marks. Phases 3 and 4 (65 marks) reuse the same pipeline, so most work below pays twice.

---

## 1. Phase 2 checklist against the repo

| Evaluation-sheet item | Status | Evidence | Gap |
|---|---|---|---|
| **Two-tier, authenticated link** | Done (verified live) | Separate `collector/` and `saas/`; key plus HMAC over the exact body; HTTPS with TLS 1.2+, server certificate and name verified against a pinned CA, behind the failover proxy. `demo.ps1 tls` shows plain HTTP refused, a different CA rejected and a tampered body returning 401 | Private dev CA only; no client certificates (mTLS) |
| **Collect → filter/redact → aggregate → analyse → policy → send** | Done (verified) | Any-format parsers, 5-second windows, local failed-login bursts, the `policy.yaml` gate, strict schema, outbox; counters at `/local/pipeline` | No stage-by-stage page yet (E6); the collector's own health verdict is a constant |
| **Allow-listing, secret scrubbing, pseudonymous IDs** | Done (verified) | Schema plus `policy.yaml`; secrets never reach the outbox (tests, the `secret` scenario, a browser check of the egress panel) | Scrubbing is pattern-based; free text has no field to travel in, so a missed secret still cannot leave |
| **Auth, TLS, audit** | Done (verified) | Key plus HMAC; TLS; one-time-token enrollment end to end; every payload kept in the local outbox with its raw record IDs (`/local/lineage/<id>`); a platform audit table | Audit is not tamper-evident; the credentials file is protected by the operating system only |
| **Telemetry: CPU, memory, disk, bandwidth, latency, packet loss** | Done (verified) | Real readings from this machine with the simulator off: CPU, memory, disk, bandwidth, plus probe latency, loss and reachability | "Loss" is failed TCP connects, not ICMP (ICMP was blocked on this machine) |
| **AIOps beyond static thresholds** | Done (verified live) | Rolling median/MAD baseline, two-window persistence, 120-second correlation, explanations and lineage; 200 alerts became 14 incidents (`/v1/noise`) | False-alarm rate on a normal stream is not measured; confidence is a heuristic |
| **Scales to many collectors and tenants** | Built, not measured | Stateless replicas, row-level security and tenant isolation tested on Postgres (the database tests run and pass); a load tool exists | Only a 20-payload smoke probe is recorded, so there is no throughput figure; the per-tenant advisory lock is a known limit; no queue |
| **Regional ingest and residency** | Built and tested, not shown live | A credential is bound to a region and a wrong region is refused; each region has its own database with a binding check; two-region tests pass and CI provisions both | One region runs live; geographic residency is a design answer, not something the prototype proves |
| **UTC, out-of-order, idempotent** | Done (verified live) | UTC enforced; events ordered by event time; duplicates stored once; same ID with a different body is a conflict (`delivery` scenario); zero loss by payload-ID set through an outage and through killing a replica | None known |

Evidence judges will ask for: an **architecture diagram with every hop labeled** (`docs/p2/trust-boundary.svg`, and a flow chart in `docs/p2/architecture.md`); the payload schema and allow-list (`contracts/payload.schema.json`, `collector/policy.yaml`); behaviour when the platform is unreachable (verified live: buffered, then zero missing by ID set); and the tenant-isolation approach (row-level security, database tests pass).

The collector/platform seam has tests in both directions: `collector/tests/test_saas_compat.py` and `saas/tests/test_contract_compat.py`. The platform validates every payload against `contracts/payload.schema.json`.

---

## 2. What is still open from Phase 1

- [x] `docs/p1/security-and-data-protection.md`, `docs/p1/story-and-plan.md` and `docs/p1/saas-and-aiops.md` all exist.
- [x] The trust-boundary sketch is now a visual: `docs/p2/trust-boundary.svg`.
- [x] The plan documents no longer describe Docker packaging (the README says "no Docker" on purpose).
- [ ] Member names are still blank in `docs/phase-1.md` and in section 4 below, and the README team line is generic.
- [ ] Q1 and Q2 are in `docs/p1/story-and-plan.md`; the team should read them and confirm they are in its own words, because judges ask the team directly.
- [ ] `docs/phase1.md` and `docs/phase-1.md` have near-identical names; merge or rename.
- [ ] Confirm the organizers' real checkpoint times, since the 24-hour timeline is ours, and the organizer stream format is still unknown.
- Done since Phase 1: a running pipeline exists, so the "feasible in 24 hours" claim is demonstrable.

---

## 3. Foundry-inspired design

These are concepts borrowed from Palantir Foundry's approach, not its branding or code. Each maps onto work we already half-have, and none of it changes the frozen payload contract (it is all SaaS-side or collector-local).

| Foundry idea | What it means for Signal Labs | Why it helps the score |
|---|---|---|
| **Ontology**: business objects and links, not tables | Model the estate as objects: Tenant, Collector, Source, Observation, Incident, Recommendation, RemediationAction, with typed links. Expose them through one object API | Phase 4 "explainable AIOps": every incident can be walked to its evidence |
| **Data lineage** | Follow one record end to end: raw record (local) → redactions → payload → stored observation → anomaly signal → incident → recommendation → action. `payload_id` is the only key that crosses the trust boundary | Answers "what data led to this recommendation?" and proves nothing raw left |
| **Markings / classification** | Tag every field with a classification (e.g. `LOCAL_ONLY`, `PSEUDONYMIZED`, `ALLOWED_METADATA`) in a policy file that the collector enforces and the egress panel displays | Phase 2 "allow-list mechanism" becomes data you can show, not code you have to explain |
| **Actions** (governed writeback) | Remediation as action types with parameters, submission criteria, an approval step, an audit record and a rollback plan | Bonus "safe remediation" and the Phase 4 live "remediation proposed" scenario |
| **Pipeline view and health** | A stage-by-stage view of the collector pipeline with counts (received, parsed, redacted, dropped, aggregated, queued, sent) | Makes the Phase 2 data flow visible live |
| **Workshop-style operational apps** | Object-centric screens: open an incident and see its collector, source, evidence, recommendation and actions in one place, with links | Judges see a story, not a table |

**Status.** The ontology, lineage, simulated actions (audited, with a rollback plan), markings (`policy.yaml`, shown in the egress panel) and the Object explorer and Health history screens are built, and the platform APIs were verified live. The collector's pipeline view is counters only. The dashboard's incident workspace, action buttons and lineage screen were built by Member 2 and have not been checked by Member 1.

### API (built by Member 2; shapes in `contracts/api.md`)

| Endpoint | Returns |
|---|---|
| `GET /v1/ontology` | object types, their properties and markings, and link types |
| `GET /v1/objects/{type}` and `/{id}` | the object plus its linked objects (e.g. Incident → collector, source, observations, recommendation, actions) |
| `GET /v1/lineage/incident/{id}` | recommendation ← signals ← payload IDs ← collector |
| `GET /v1/lineage/payload/{id}` | which signals and incidents used this payload |
| `GET /v1/actions`, `POST /v1/actions/propose`, `/{id}/approve`, `/{id}/reject`, `/{id}/rollback` | action lifecycle with audit trail |
| `GET /v1/noise` | raw alerts vs. incidents (noise-reduction ratio) |

Collector-local (built, and answering this machine only, 403 otherwise): `/local/policy`, `/local/pipeline`, `/local/lineage/{payload_id}`, `/local/ui`, `/local/host`, `/local/retention`, `/local/identity`.
The local half of lineage (raw record, redactions) stays on the collector and is never served by the SaaS.

---

## 4. Work split for two people

| | Member 1: Edge | Member 2: Platform |
|---|---|---|
| **Name** | _______ | _______ |
| **Owns** | `collector/**`, `simulator/**`, `scripts/**`, `deploy/**`, `contracts/payload.schema.json`, `.env.example`, `docs/p1/security-*`, `docs/p2/collector.md` | `saas/**`, `dashboard/**`, `.github/**`, `contracts/api.md`, `README.md`, `starter.md`, `docs/phase-*.md`, `docs/p1/saas-*`, `docs/p1/story-*`, `docs/p2/saas.md`, `docs/p2/architecture.md` |
| **In one line** | Everything inside the customer environment, plus how the system is started, driven and demonstrated | The central platform and everything the judges see |

Why this split: the dashboard depends on the SaaS API shapes, so one person building both removes the slowest handoff. The two halves meet in only four places (section 5), so they can work almost independently.

**Branches:** `edge/<topic>` and `platform/<topic>`. Rebase on `main` before every PR, and merge at least every two hours.
**Shared-file rule:** nobody edits a file the other owns. If you need a change there, message them; for `contracts/payload.schema.json` Member 1 edits and Member 2 approves.

Priority: **P0** = a Phase 2 or Phase 3 tick or a mandatory item; **P1** = strengthens Phase 4 or a bonus; **P2** = if time remains.

### Member 1: Edge (collector, security, telemetry, running and demonstrating)

| ID | P | Task | Files | Done when |
|---|---|---|---|---|
| E1 | P0 | **Aggregate and analyse locally.** 5 s windows per source and metric (avg, max, count); failed-login burst detector (count per source per window) emitting one `auth_failure_burst` event | `collector/aggregate.py`, `local_analysis.py`, `pipeline.py` | 40 failed-login lines produce 1 event with `count=40` and zero per-line events |
| E2 | P0 | **Policy as data ("markings").** `collector/policy.yaml` lists each field, its classification and treatment; the pipeline enforces it; `GET /local/policy` serves it | `collector/policy.yaml`, `policy.py` | Removing a field from the policy stops it leaving (test), and the panel can list it |
| E3 | P0 | **TLS.** HTTPS from collector to SaaS with a self-signed CA and a cert script; collector verifies the CA. Member 2 only adds the uvicorn TLS flags to the run docs | `scripts/gen-certs.ps1`, `collector/sender.py` | Plain HTTP is refused, HTTPS works, a tampered body returns 401 |
| E4 | P0 | **Real host telemetry.** CPU, memory, disk, network bandwidth via `psutil`; latency and packet loss via a probe to a configured target | `collector/sources/host.py`, `requirements.txt` | The collector reports all six metrics with the simulator switched off |
| E5 | P0 | **Real egress proof panel** (collector-local page): raw record with secrets beside the exact payload, redactions highlighted | `collector/ui/`, served at `/local/ui` | A secret appears on the left and is absent on the right, for a real record |
| E6 | P1 | **Pipeline stage counters** and a stage view (received, parsed by format, redacted by rule, dropped by policy, aggregated, queued, sent) | `collector/stats.py`, `GET /local/pipeline` | Counts per stage add up; drops by rule are visible |
| E7 | P1 | **Retention and limits.** Scheduled raw purge, outbox size cap with a drop policy, line size cap | `collector/outbox.py`, `main.py` | Old raw records are deleted on schedule; a flood cannot fill the disk |
| E8 | P1 | **Enrollment, collector side** (pairs with P3) | `collector/enroll.py` | A fresh collector registers itself and starts reporting without manual keys |
| E9 | P2 | **Local lineage lookup** `GET /local/lineage/{payload_id}` (raw ID, redaction rules, send status) | `collector/outbox.py`, `main.py` | Given a payload ID from an incident, the collector shows its raw record |
| E10 | P0 | **Simulator parity and scenarios.** Add disk, bandwidth, packet loss and connectivity; scenarios for packet loss, disk, alert storm, duplicate and out-of-order delivery and outage; one `scripts/demo_<scenario>.ps1` per live scenario, each stating the expected result | `simulator/`, `scripts/` | All 8 judge scenarios run from one command each |
| E11 | P0 | **One-command local run**, since Docker is gone: Postgres cluster, migration, two replicas, collector, simulator, dashboard, plus a stop script | `scripts/run-local.ps1`, `stop-local.ps1` | A clean checkout runs with one command |
| E12 | P0 | **Failover proxy.** A small round-robin proxy that preserves exact request bytes (HMAC) and fails over between replicas, restoring the "kill a replica" demo without nginx | `scripts/lb.py` | Killing replica 1 mid-stream loses and duplicates nothing |
| E13 | P0 | Docs: `docs/p1/security-and-data-protection.md`, the collector half of the Phase 2 write-up (`docs/p2/collector.md`: pipeline, markings, TLS, retention, trust boundary with every hop labeled) and the trust-boundary one-pager as a visual | `docs/` | Covers every collector-side line of the Phase 2 sheet |

### Member 2: Platform (SaaS, ontology, actions, AIOps, dashboard, story)

| ID | P | Task | Files | Done when |
|---|---|---|---|---|
| P1 | P0 | **Ontology layer.** Declarative object and link registry; `GET /v1/ontology`, `/v1/objects/{type}[/{id}]`; built on existing tables | `saas/ontology.py`, `saas/main.py` (routes) | An Incident object returns its collector, source, evidence payloads, recommendation and actions |
| P2 | P0 | **Action types.** Registry (restart service, isolate source, rotate credentials, scale capacity) with parameters, policy check, propose → approve/reject, audit entry and rollback plan; replaces the single `approve` | `saas/actions.py`, `saas/migrations/002.sql` | Full lifecycle works under roles, with audit rows and a rollback record; nothing is executed |
| P3 | P1 | **Enrollment endpoint** `POST /v1/enroll` plus admin token creation; DB-backed credentials replace the static `SAAS_AUTH_JSON` | `saas/enroll.py`, `002.sql` | A one-time token yields collector credentials once, then is spent |
| P4 | P0 | **Contract enforcement.** Make the SaaS honour `contracts/payload.schema.json` (or generate `schema.py` from it) and remove the strictness drift; add a two-way compat test with Member 1 | `saas/schema.py`, `saas/tests/` | A payload the contract forbids is rejected by the SaaS, and the compat test fails on drift |
| P5 | P1 | **Lineage API** for incidents and payloads | `saas/lineage.py` | An incident resolves to its payload IDs and back |
| P6 | P1 | **AIOps quality.** Require persistence across N windows, derive confidence from signal agreement, add `GET /v1/noise`, test against injected scenarios for false alarms | `saas/aiops.py`, `correlation.py`, tests | The simulator's normal stream raises no incident; injected spikes raise exactly one |
| P7 | P1 | **Second tenant and second region.** `t-globex` in region `eu` on a separate database; cross-region ingest refused | `saas/` config | Two tenants never see each other; each region's data lives only in its own database |
| P8 | P2 | **Scale evidence.** Load script (N collectors × M tenants) and a throughput note, including the advisory-lock limit | `saas/tools/loadtest.py` | A stated number, with the bottleneck named |
| P9 | P0 | **Object pages (Workshop-style).** Incident workspace showing collector, source, evidence, recommendation and actions with links; a simple object explorer | `dashboard/src/pages/`, `api.js` | From an incident you can click through to every linked object |
| P10 | P0 | **Actions UI.** Propose, approve, reject, roll back, with an audit timeline, in the incident view | `dashboard/src/` | The live "remediation proposed" scenario can be run from the UI |
| P11 | P0 | **Lineage and health-history views.** Lineage chain per incident; four-state history with reasons and UTC timestamps | `dashboard/src/` | A recommendation shows the payload IDs behind it; a state change shows when and why |
| P12 | P1 | **Live updates and a clean latency window.** Use `/v1/stream`; scope the latency figure to a recent window | `dashboard/src/api.js` | A fresh measurement window can be taken on a steady stream |
| P13 | P1 | **CI.** Python tests plus `npm ci && npm run build` | `.github/workflows/ci.yml` | Passes on push |
| P14 | P0 | Docs and story: `docs/p1/story-and-plan.md` (Q1, Q2 in your own words, names), fix `docs/p1/saas-and-aiops.md`, `docs/p2/saas.md` (HA, residency, UTC, out-of-order, idempotency, scaling), the Phase 2 architecture diagram with every hop labeled (`docs/p2/architecture.md`, built from Member 1's collector half), and removal of Docker references from `starter.md` and `docs/phase-1.md` | `docs/`, `README.md`, `starter.md` | Every Phase 1 box in section 2 is ticked |

**Shared, no owner conflict:** slides and Q&A rehearsal (both of you present and answer), and a final run of all 8 live scenarios together.

### Rough load

Member 1 has 13 tasks (7 P0); Member 2 has 14 (8 P0), but P9 to P11 are screens on APIs Member 2 also builds, so they have no waiting time. If Member 2 falls behind, hand P8, P12 and P13 to Member 1; if Member 1 falls behind, hand E9 and E6 to Member 2.

### Task status

| ID | Status | Notes |
|---|---|---|
| E1 | Done (verified) | 40 failed-login lines become one event with `count=40`; no per-line events |
| E2 | Done (verified) | `policy.yaml` enforced, fails closed, served at `/local/policy` |
| E3 | Done (verified live) | TLS with a verified, pinned CA; `REQUIRE_TLS` refuses plain HTTP |
| E4 | Done (verified live) | Real host readings with the simulator off |
| E5 | Done (verified in a browser) | Raw beside exact payload, with a leak check; an injected `<script>` stayed inert |
| E6 | Partial | Counters at `/local/pipeline`; no stage page |
| E7 | Done (verified live) | A 40,000-line flood left 500 raw rows, 201 pending payloads and 0.3 MiB; every drop counted and reported |
| E8 | Done (verified live) | A collector with no keys enrolled itself; the token is single-use |
| E9 | Done | Served as `/local/lineage/<id>` and used by the egress panel |
| E10 | Done | 14 scenarios, each stating its expected result |
| E11 | Done | `scripts/run-local.ps1` and `stop-local.ps1` |
| E12 | Done (verified live) | Killing replica 1 mid-stream: 0 payloads missing, 0 duplicates stored |
| E13 | Done | Collector docs and the trust-boundary diagram |
| P1 | Done (verified) | Ontology and object endpoints; an incident resolves to its collector, source, evidence, recommendation and action |
| P2 | Done (verified live) | Policy refusal, propose, approve, roll back, audit trail, blocked invalid transition; simulation only |
| P3 | Done (verified live) | Token creation (admin role) and enrollment endpoint, used by the `enroll` scenario |
| P4 | Done (verified) | Platform validates against the frozen contract and accepts everything the collector produces |
| P5 | Done (verified) | Lineage endpoints for incidents and payloads |
| P6 | Mostly done | Two-window persistence and `/v1/noise` verified; false-alarm rate on a normal stream not measured |
| P7 | Built and tested | Region-bound databases and two-region tests; not shown live |
| P8 | Partial | Tool exists; only a 20-payload smoke probe is recorded, no capacity figure |
| P9 | Partly checked | Object explorer renders live data; the incident workspace was not checked |
| P10 | Built, not checked in a browser | The action lifecycle was verified through the API |
| P11 | Partly checked | Health history renders live data; the lineage screen was not checked |
| P12 | Built, not checked | Live updates and a five-minute proof window exist in the dashboard code |
| P13 | Done | CI is green with a Postgres service; the TLS tests skip there because CI does not install `cryptography` |
| P14 | Done | Docs exist; this update corrects the statements that had gone stale |

---

## 5. The four seams (where the two halves meet)

| Seam | Owner of each side | Rule |
|---|---|---|
| **Payload contract** (`contracts/payload.schema.json`) | Member 1 edits, Member 2 approves | No new payload field without both agreeing. Nothing in this plan needs one |
| **Ingest and heartbeat API** | Member 2 defines, Member 1 calls | Collector changes (E1, E4) must keep `collector/tests/test_saas_compat.py` green |
| **TLS and credentials** | Member 1 (certs, client), Member 2 (server flags, enrollment) | Agree the cert paths and env var names once, then freeze |
| **Telemetry coverage** | Member 1 produces (E4, E10), Member 2 consumes (P6, P9) | Metric names stay on the allow-list in `collector/schema.py` |

Order of work: Member 1 starts with E1, E2, E10, E11; Member 2 starts with P4, P1, P2. Then E3, E4, E5, E12 against P9 to P11. Then the P1 items. Merge to `main` at least every two hours. Freeze features with enough time left to rehearse all 8 live scenarios against the organizer stream.

## 6. Done checklist for Phase 2 (tick from the running system)

- [x] Two tiers over TLS with authenticated collectors (E3)
- [ ] Pipeline visible stage by stage, including aggregate and local analysis: the stages run and the counters are served at `/local/pipeline`, but there is no stage page (E6)
- [x] Allow-list and markings shown from a policy file (E2, E5)
- [x] All six telemetry types collected from a real host (E4)
- [x] An anomaly beyond a static threshold, with its explanation and lineage: verified through the API (P1, P5); the dashboard's lineage screen was not checked (P11)
- [ ] Multi-tenant and multi-region isolation demonstrated: tenant isolation is tested on Postgres, and the second region is tested but not shown live (P7)
- [x] UTC, out-of-order and duplicate delivery shown live (E10)
- [x] Architecture diagram with every hop labeled (`docs/p2/trust-boundary.svg`)

## 7. Open items that affect later phases

- **Real-time targets are not cleanly measured.** The sheet asks for dashboard ≤ 10 s (p95), alert ≤ 15 s and offline detection ≤ 60 s, measured from timestamps. Figures seen so far (13.8 s dashboard p95, 16.8 s alert delay) were skewed by an old measurement window and by test events timestamped in the past, so they should not be quoted. Take a fresh measurement on a steady live stream.
- **No scale figure.** Run the load tool and record a throughput number with its bottleneck named (P8).
- **Organizer stream not integrated.** Its format is unknown; a new collector parser is a small change once it is published.
- **Rehearsal.** Run all 14 scenarios together against the organizer stream before the final.
- **CI skips the TLS tests** until `cryptography` is installed there.
- **Dashboard screens P9 to P12** need a check in a browser.
