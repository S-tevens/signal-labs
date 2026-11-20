> Historical Phase 1 planning document. Packaging and ownership have changed; use `README.md` for the native run instructions and `docs/phase-2.md` for the current team split. Earlier load-balancer and packaging ideas below are historical proposals, not available run commands.

# Phase 1 — Team Work Split (3 members, minimal merge conflicts)

Goal: finish the Phase 1 deliverables **and** lay the scaffold for the build, with every person working in files nobody else touches.

Names: replace **Member A / B / C** with real names in the table below.

| Member | Name | Area | One-line mission |
|---|---|---|---|
| **A** | _______ | Collector & security | Everything inside the customer environment, plus the payload contract |
| **B** | _______ | SaaS & AIOps | Everything on the central platform |
| **C** | _______ | Dashboard, simulator & story | What judges see, the data that feeds it, and the pitch |

---

## 1. The rule that prevents conflicts: one owner per path

**Each path has exactly one owner. Only the owner edits it.** If you need a change in someone else's path, ask them or open a PR that they approve.

| Path | Owner | Notes |
|---|---|---|
| `collector/**` | A | adapters, redaction, aggregation, outbox, sender, local UI |
| `contracts/**` | A (B must approve changes) | payload schema and API contract, **frozen after hour 1** |
| `docs/p1/security-and-data-protection.md` | A | |
| `saas/**` | B | ingest, auth, store, health, aiops, remediation, proof |
| `docs/p1/saas-and-aiops.md` | B | |
| `dashboard/**` | C | React app |
| `simulator/**` | C | stream generator and scenario injectors |
| `scripts/**` | C | demo scripts |
| `deploy/**` | C | load balancer config, install and enrollment scripts, CI workflow (A and B tell C what their services need) |
| `scripts/`, `.env.example` | Edge owner | Coordinate native launch settings with the platform owner |
| `docs/p1/story-and-plan.md` | C | |
| `docs/phase-1.md` (this file), `README.md`, `starter.md` | C | others suggest edits in chat |
| `docs/phase1.md` | C | existing combined draft; split content into the three `docs/p1/` files, then keep it as the summary |

**Never shared:** no one edits `README.md` or root-level config files unless they own them. Each package keeps its **own** dependency file (`collector/requirements.txt`, `saas/requirements.txt`, `dashboard/package.json`), so there is no shared lock file to collide on.

---

## 2. Git workflow

1. `main` is always runnable. Nobody commits directly to it after the scaffold lands.
2. Branch names: `a/<topic>`, `b/<topic>`, `c/<topic>` (e.g. `a/redaction`, `b/health-engine`, `c/proof-view`).
3. Rebase onto `main` before opening a PR: `git fetch && git rebase origin/main`.
4. Small PRs, merged at least **every 2 hours**. Long-lived branches are where conflicts come from.
5. Merge order when two PRs are ready: contract changes first, then collector/SaaS, then dashboard.
6. Commit messages: short, imperative, plain text (e.g. `Add secret scrubber`). Do not add co-author or tool attribution lines.
7. Never reformat files you do not own, and never commit generated files (`node_modules/`, `__pycache__/`, `*.db`, `.env`). Add the root `.gitignore` in the very first commit (C does this).
8. If you hit a conflict, **stop and message the owner**; do not resolve it by overwriting their version.

---

## 3. Interface contract (agree in hour 1, then freeze)

Because the three areas only meet at these interfaces, agreeing on them first lets everyone build in parallel without touching each other's code. A drafts, B approves, C reads.

### 3.1 Egress payload — `contracts/payload.schema.json`
Fields: `payload_id, tenant_ref, collector_id, source_id, region, event_ts_utc, source_tz, window_s, metric{name,value,unit} | event{category,severity,count,summary}, health_state, collector_version` (see `docs/phase1.md` §6). Extra fields are rejected.

### 3.2 Ports and URLs

| Service | Port | Owner |
|---|---|---|
| Collector (tenant 1) | 8101 | A |
| Collector (tenant 2) | 8102 | A |
| SaaS replica 1 | 8000 | B |
| SaaS replica 2 | 8001 | B |
| Load balancer (the one SaaS URL collectors use) | 8080 | C |
| Postgres | 5432 | Edge (local setup), Platform (schema) |
| Dashboard dev server | 5173 | C |

### 3.3 SaaS API (B implements, A and C consume) — `contracts/api.md`

| Method and path | Caller | Purpose |
|---|---|---|
| `POST /v1/ingest` | collector | send one payload or a batch; response lists `accepted` and `duplicate` IDs |
| `POST /v1/heartbeat` | collector | liveness, version, resource usage, config hash |
| `GET /v1/fleet` | dashboard | collectors with state, last seen, version |
| `GET /v1/metrics?source=&name=&from=&to=` | dashboard | time series ordered by event time |
| `GET /v1/incidents` | dashboard | correlated incidents with recommendations and explanation |
| `GET /v1/health/history` | dashboard | UTC-timestamped state transitions with reasons |
| `GET /v1/proof` | dashboard | p95 latency, alert delay, offline-detection time, sent vs. received counts |
| `POST /v1/remediation/{id}/approve` | dashboard | approval step (simulated) |
| `GET /v1/stream` | dashboard | server-sent events for live updates |

Auth on collector calls: `X-Collector-Key` header plus `X-Signature` (HMAC of the body). The tenant comes from the key, never from the body.

### 3.4 Collector local API (A implements, C consumes in the demo UI) 

| Method and path | Purpose |
|---|---|
| `GET /local/raw` | recent raw records (secrets visible) — local view only |
| `GET /local/egress` | egress log: exact payloads sent, with the raw record each came from |
| `GET /local/buffer` | outbox depth, last send, retry state |
| `POST /local/saas-link/{up|down}` | demo switch to simulate a SaaS outage |

### 3.5 Input formats (C produces, A consumes)
The organizer said traffic can be **any format**, so the collector must not assume one. A auto-detects and parses JSON, syslog, plain text, CSV, key=value, SNMP and flow data into one internal model (`collector/parsers/`, one file per format, so adding a format never touches another file). C's simulator emits several of these formats so the parsers get exercised. The JSON-lines shape below is only the default example.

JSON lines, one object per line, over `POST /ingest/jsonl` on the collector. Shape (until the organizer format is published):
`{"ts": "<ISO-8601 UTC>", "tz": "Asia/Kolkata", "host": "...", "kind": "metric|log|heartbeat", ...}`.
When the organizer stream format is known, **A** writes a new adapter in `collector/adapters/`; C's simulator is not changed.

**Change process:** to change anything in §3, the proposer posts the change in the team chat, A edits `contracts/`, B approves, and the PR merges before anyone codes against it.

---

## 4. Phase 1 deliverables, split by file

Each person writes **their own file** in `docs/p1/`, so the three documents can be written in parallel with zero overlap. C then links them from `docs/phase-1.md`.

| Evaluation-sheet item | File | Writer |
|---|---|---|
| Local data protection: what stays local, what is redacted, what is sent | `security-and-data-protection.md` | A |
| Allow-listed fields and redaction examples (the judge's evidence) | same | A |
| Trust-boundary sketch (one page, every hop labeled) | same | A |
| Why raw telemetry stays local | same | A |
| Metadata-only SaaS flow: tenant separation, who can see what | `saas-and-aiops.md` | B |
| Global concerns: regions, residency, UTC, ordering, idempotency | same | B |
| Four health states and thresholds (draft) | same | B |
| AIOps outline: baseline, correlation, explanation | same | B |
| Q1: before observability | `story-and-plan.md` | C |
| Q2: what we now observe | same | C |
| Use cases (infra, network, failed logins, fleet) | same | C |
| Prioritized features and MVP | same | C |
| 24-hour plan, roles, simulated-telemetry plan, risks | same | C |
| One-minute pitch | same | C |

Starting material for all of it is already in [phase1.md](phase1.md); copy the relevant section into your file, then improve and personalize it.

---

## 5. Task list per member

### Member A — Collector & security

**Docs (hours 0–2):** `docs/p1/security-and-data-protection.md`.

**Contract (hour 0–1):** draft `contracts/payload.schema.json` and the collector parts of `contracts/api.md`; hand to B for approval.

**Scaffold (hours 1–2), only inside `collector/`:**
- `collector/main.py` (FastAPI app), `requirements.txt` and native launch instructions
- `collector/parsers/` with a small plugin interface (`detect(raw) -> bool`, `parse(raw) -> Record`) and the first two parsers (JSON, syslog)
- `collector/enroll.py`: first start exchanges a one-time enrollment token for the collector key and config
- `collector/schema.py` (Pydantic model generated from or matching the contract, `extra="forbid"`)
- `collector/redact.py` stub with the first patterns (password=, token=, Bearer, AWS key, JWT, email)
- `collector/outbox.py` stub (SQLite table: `payload_id`, `body`, `status`)
- `collector/tests/` for redaction and schema rejection

**Done when:** a raw log line containing a secret enters `POST /ingest/jsonl`, and `GET /local/egress` shows a payload with the secret gone.

### Member B — SaaS & AIOps

**Docs (hours 0–2):** `docs/p1/saas-and-aiops.md`.

**Contract (hour 0–1):** review and approve A's contract; write the SaaS response shapes in `contracts/api.md` through A.

**Scaffold (hours 1–2), only inside `saas/`:**
- `saas/main.py` (stateless FastAPI app: all state lives in Postgres, `REPLICA_ID` env var), `requirements.txt` and native launch instructions
- `saas/auth.py` (key to tenant lookup from a static seed file)
- `saas/ingest.py` with dedup on `payload_id` (unique constraint in Postgres so any replica rejects duplicates; returns `accepted` and `duplicate`)
- `saas/store.py` (Postgres, `tenant_id` on every table, row-level security so a query can only see its own tenant)
- `saas/config/thresholds.yaml` (four health states)
- `saas/tests/` for dedup, tenant isolation and out-of-order placement

**Done when:** `POST /v1/ingest` with a duplicate ID returns it under `duplicate`, and `GET /v1/fleet` shows the collector for the correct tenant only.

### Member C — Dashboard, simulator & story

**Docs (hours 0–2):** `docs/p1/story-and-plan.md`, then update `docs/phase-1.md` to link all three files.

**Scaffold (hours 0–2), in this order:**
1. Root `.gitignore` and `.env.example` (first commit, so nobody else needs to touch them)
2. A native one-command local start script is planned; see the current edge/platform work split in `docs/phase-2.md`.
3. `simulator/` generator producing the JSON-lines shape in §3.5: metrics, auth logs (some with secrets), heartbeats, plus a `scenarios/` folder with one script per live scenario
4. `dashboard/` Vite + React skeleton with routes for Fleet, Incidents, Proof, Egress; data from mock JSON that matches `contracts/api.md`, so it works before B finishes

**Done when:** the planned local start script starts all services, the simulator feeds the collector, and the dashboard renders the Fleet page (mock data is fine at this stage).

---

## 6. Hour-by-hour sync points

| Hour | Event | Who |
|---|---|---|
| 0:00 | 15-minute kickoff: confirm ownership table, ports, branch rules | all |
| 0:00–1:00 | A drafts contract, B reviews, owners agree on local launch and configuration | A, B, C |
| **1:00** | **Contract freeze.** Merge `contracts/` and the root files into `main` | A, B, C |
| 1:00–2:00 | Everyone scaffolds their own folder, writes their `docs/p1/` file | all |
| **2:00** | **Phase 1 review:** read the three docs together, check against the evaluation sheet, rehearse Q1/Q2 and the pitch | all |
| 2:00 | Merge everything; first end-to-end smoke test (simulator → collector → SaaS) | all |

After hour 2, continue with the timeline in [starter.md](../starter.md): merge to `main` every 2 hours, and re-sync whenever the contract must change.

---

## 7. Conflict checklist (read before every push)

- [ ] I only changed files under paths I own.
- [ ] I rebased on `origin/main` just now.
- [ ] I did not edit `contracts/` or `README.md` unless I own them.
- [ ] No generated files, databases or secrets are staged (`git status`).
- [ ] If I need a change in someone else's area, I messaged them instead of editing it.
- [ ] The PR is small enough to review in five minutes.

---

## 8. Phase 1 completion checklist (tick before presenting)

- [ ] Names filled in at the top of this file
- [ ] `docs/p1/security-and-data-protection.md` written by A (trust boundary, allow-list, redaction examples)
- [ ] `docs/p1/saas-and-aiops.md` written by B (tenant separation, global concerns, health states, AIOps outline)
- [ ] `docs/p1/story-and-plan.md` written by C (Q1, Q2, use cases, MVP, plan, pitch)
- [ ] Q1 and Q2 rewritten in the team's own words
- [ ] Contract merged and frozen
- [ ] Scaffold merged; the planned local start script runs without errors
- [ ] Every member can explain the whole flow in 60 seconds, not only their own part

---

## 9. Organizer clarifications (what changed in the split)

> "SaaS can be uniform, central and high availability. Traffic format can be anything, to have accurate data and optimization. Build a secure, automated, packaged system which will want to observe everything."

| Note | Owner | Work |
|---|---|---|
| High-availability central SaaS | B (app), Edge (launch, planned failover proxy) | 2 stateless replicas, shared Postgres, DB-enforced dedup, "kill one replica" demo script |
| Any traffic format | A (parsers), C (multi-format simulator) | parser plugins plus format auto-detect; batching and gzip to optimize what is sent |
| Secure | A, B | TLS, API key, HMAC, allow-list, scrubbing (unchanged) |
| Automated | A (enroll), C (CI, one-command start) | one-time enrollment token; CI builds and tests on every push |
| Packaged | A, B, C | Native run instructions exist; one-command startup and installer are planned |
| Observe everything | A | one parser plugin per source type: infrastructure, network, applications, security |

The guide's regional ingest and residency requirements stay in the design write-up (B's `saas-and-aiops.md`), but the live demo uses the single central SaaS.
