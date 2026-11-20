# Phase 2 — Architecture & Technical Design: status, Foundry-inspired design, and work split

Status as of the last merge to `main`. "Verified" means we ran it; "design only" means it is described but not built.
Two people share the work: **Member 1 (Edge)** owns everything inside the customer environment and the way the system is run and demonstrated; **Member 2 (Platform)** owns the central SaaS and everything the judges see on the dashboard. Put your names next to these in section 4.

Judges tick only what is demonstrated live, and Phase 2 is 25 marks. Phases 3 and 4 (65 marks) reuse the same pipeline, so most work below pays twice.

---

## 1. Phase 2 checklist against the repo

| Evaluation-sheet item | Status | Evidence in the repo | Gap |
|---|---|---|---|
| **Two-tier, authenticated link** | Partial | Separate `collector/` and `saas/`; per-collector key plus HMAC over exact bytes; identity taken from the credential, never the body | **No TLS**: plain HTTP, and the load balancer went out with Docker |
| **Collect → filter/redact → aggregate → analyse → policy → send** | Partial | Any-format parsers, redaction, strict allow-list schema, outbox and signed send are built | **No aggregation and no local analysis**: every record becomes one payload (`window_s=1`), so failed logins are not counted into a burst |
| **Allow-listing, secret scrubbing, pseudonymous IDs** | Done | `collector/schema.py` (extra fields forbidden), `redact.py`, HMAC `src_…` IDs; tests prove secrets never reach the outbox | Policy is code, not data (see E2) |
| **Auth, TLS, audit** | Partial | Auth done. Local egress log and a SaaS `audit` table exist | **TLS missing.** Retention (`purge_raw`) exists but never runs. Audit is not tamper-evident |
| **Telemetry: CPU, memory, disk, bandwidth, latency, packet loss** | Partial | All six are in the schema and SaaS thresholds | Collection is simulated only, and only CPU, memory and latency. **Nothing reads a real host**; disk, bandwidth and packet loss are never produced |
| **AIOps beyond static thresholds** | Done (not DB-tested) | Rolling median/MAD baseline, 120 s correlation window, incidents with a recommendation and "why" (`saas/aiops.py`, `correlation.py`) | No persistence rule yet, so false alarms are likely; DB integration tests are skipped here |
| **Scales to many collectors and tenants** | Partial | Stateless replicas, one Postgres with row-level security, per-tenant isolation | Per-tenant advisory lock limits one big tenant; **no load test, no queue** |
| **Regional ingest and residency** | Design only | Credential carries a region and a wrong-region request is refused (403) | One region live. No second region or separate store demonstrated |
| **UTC, out-of-order, idempotent** | Done (not DB-tested) | UTC enforced, events ordered by event time, payload IDs deduplicated, same ID with a different body is a conflict | B's DB tests have never run here |

Evidence judges will ask for: an **architecture diagram with every hop labeled** (missing), the payload schema and allow-list mechanism (exists), behaviour when SaaS is unreachable (verified), and the tenant-isolation approach (row-level security, DB tests unrun).

Drift risk: the SaaS validates with its own `saas/schema.py`, and `contracts/payload.schema.json` is no longer read by the SaaS. Only the one-way compat test in `collector/tests/test_saas_compat.py` guards the seam (task P4).

---

## 2. What is still open in Phase 1

- [ ] `docs/p1/security-and-data-protection.md` (Member 1) and `docs/p1/story-and-plan.md` (Member 2) do not exist; only the SaaS document is there.
- [ ] Member names are blank in `docs/phase-1.md` and the README.
- [ ] Q1 and Q2 are generic. They must be rewritten in the team's own words, because judges ask the team directly.
- [ ] The trust-boundary sketch is ASCII in a markdown file; export it as a one-page visual.
- [ ] `docs/p1/saas-and-aiops.md` still mentions the Dockerfile, load balancer on 8080 and Postgres on 5432.
- [ ] `starter.md` and `docs/phase-1.md` still describe Docker packaging.
- [ ] `docs/phase1.md` and `docs/phase-1.md` have near-identical names; merge or rename.
- [ ] Confirm the organizers' real checkpoint times, since the 24-hour timeline is ours.
- Done since Phase 1: a running MVP pipeline exists, so the "feasible in 24 hours" claim is demonstrable.

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

### Proposed API (Member 2 builds both the endpoints and the screens that use them; freeze the shapes in `contracts/api.md` before Member 1 depends on any of them)

| Endpoint | Returns |
|---|---|
| `GET /v1/ontology` | object types, their properties and markings, and link types |
| `GET /v1/objects/{type}` and `/{id}` | the object plus its linked objects (e.g. Incident → collector, source, observations, recommendation, actions) |
| `GET /v1/lineage/incident/{id}` | recommendation ← signals ← payload IDs ← collector |
| `GET /v1/lineage/payload/{id}` | which signals and incidents used this payload |
| `GET /v1/actions`, `POST /v1/actions/propose`, `/{id}/approve`, `/{id}/reject`, `/{id}/rollback` | action lifecycle with audit trail |
| `GET /v1/noise` | raw alerts vs. incidents (noise-reduction ratio) |

Collector-local (Member 1 builds): `GET /local/policy`, `GET /local/pipeline`, `GET /local/lineage/{payload_id}`.
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

- [ ] Two tiers over TLS with authenticated collectors (E3)
- [ ] Pipeline visible stage by stage, including aggregate and local analysis (E1, E6)
- [ ] Allow-list and markings shown from a policy file (E2, E5)
- [ ] All six telemetry types collected from a real host (E4)
- [ ] An anomaly beyond a static threshold, with its explanation and lineage (P1, P5, P11)
- [ ] Multi-tenant and multi-region isolation demonstrated (P7)
- [ ] UTC, out-of-order and duplicate delivery shown live (E10)
- [ ] Architecture diagram with every hop labeled (P14)
