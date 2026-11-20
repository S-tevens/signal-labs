# Phase 1 — Problem Understanding & Ideation (10 marks)

Everything here maps to a box on the evaluation sheet. Evidence the judge may ask for: a trust-boundary sketch (§5), the allow-list with redaction examples (§6), and the simulated-telemetry plan with roles (§9).

---

## 1. Why raw telemetry must stay in the customer environment

- **Attack surface:** raw logs routinely contain passwords, tokens, API keys, usernames, IPs and request payloads. Shipping them to a central platform means one breach of that platform exposes every customer.
- **Compliance:** GDPR, India's DPDP Act, HIPAA and PCI-DSS restrict moving personal or regulated data across systems and borders. Metadata (numbers, states, categories) is far easier to justify.
- **Trust:** customers adopt monitoring faster when they can verify that nothing sensitive leaves. Our **egress proof panel** makes that verifiable instead of a promise.
- **Cost and latency:** summarizing locally sends kilobytes instead of gigabytes.

**Why SaaS still works with metadata only:** health, trends, anomalies, correlation and recommendations need *numbers, timestamps, categories and severity*, not message bodies. The sensitive detail stays local and is reachable by the customer's own operators on the collector UI.

---

## 2. Q1 — Before observability: what was the situation?

*(Answer in the team's own voice; this is the "before" story.)*

- Logs and credentials were copied to a central tool, so one breach exposed everything, and compliance teams blocked adoption.
- Each site, network and application had its own tool. Nobody had a single consolidated view.
- Static-threshold alerts fired constantly and in duplicate. One real incident produced 20 pages, and operators ignored them (alert fatigue).
- Outages were discovered by users, not monitoring. A silent collector looked the same as a healthy one, because stale data showed the last good value.
- A failed-login burst was only noticed after the fact, by reading raw auth logs that could not be shared.

## 3. Q2 — Observation: what do we now observe with our solution?

- **Per-tenant fleet view** with four health states (Excellent / Good / Fair / Poor), each with the reason for its state.
- **Collector status:** online/offline, last seen, version, resource usage, config status. Silence downgrades the state.
- **Anomalies against learned baselines**, not just thresholds, with the signals that contributed.
- **One correlated incident** instead of many alerts, with affected components and a recommended action.
- **Security summaries** (e.g. "risk: high, 42 failed logins in 60 s") without any raw auth record leaving.
- **Egress proof:** for every payload, exactly what left, next to the raw record that stayed.
- **Measured delivery:** p95 latency, alert delay, offline-detection time, and sent vs. received IDs.

---

## 4. Use cases (picked for high value and 24-hour feasibility)

| # | Use case | Signals | Local processing | What SaaS sees |
|---|---|---|---|---|
| 1 | **Infrastructure health** | CPU, memory, disk, service up/down | aggregate per window | metric values, health state |
| 2 | **Network latency & packet loss** | latency ms, loss %, bandwidth, connectivity | aggregate, trend | metric values, trend, affected pseudonymous source |
| 3 | **Repeated failed logins** | auth log lines | parse, count per source, score risk | `event: auth_failure_burst`, count, severity. No usernames, IPs or lines |
| 4 | **Collector fleet health** | heartbeat, version, CPU/mem of the collector, config hash | self-monitoring | status, last seen, version, resource use |

Plus one cross-cutting use case: **correlation**, where latency + CPU + packet loss on related sources collapse into one incident.

---

## 5. Trust boundary (data-flow sketch)

```
┌──────────────────────────── CUSTOMER ENVIRONMENT (TRUST BOUNDARY) ───────────────────────────┐
│                                                                                              │
│  Apps / Servers / Network devices / Security sources                                         │
│        │  raw logs, payloads, secrets, usernames, IPs                                        │
│        ▼                                                                                     │
│  ① Collect ─► ② Raw store (LOCAL ONLY, TTL retention) ◄── Local UI (operators see raw)      │
│                      │                                                                       │
│                      ▼                                                                       │
│  ③ Filter/Redact ─► ④ Aggregate ─► ⑤ Analyze locally ─► ⑥ Policy gate (allow-list)          │
│     secret scrub       5 s windows     failed-login risk      drop anything not allowed      │
│     pseudonymize IDs                                              │                          │
│                                                                   ▼                          │
│                                  ⑦ Outbox (buffer, payload_id) ─► ⑧ Egress log (proof panel)│
│                                                                   │                          │
└───────────────────────────────────────────────────────────────────┼──────────────────────────┘
                                          TLS + collector API key + HMAC signature
                                          regional ingest endpoint, retry with backoff
┌───────────────────────────────────────────────────────────────────┼──────────────────────────┐
│  CENTRAL SAAS (multi-tenant, METADATA ONLY, tenant_id from credential)                       │
│  Ingest ─► dedup by payload_id ─► store by event time ─► health ─► AIOps ─► Dashboard        │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Nothing crosses the boundary except what the policy gate (⑥) allows, and every crossing is recorded in the egress log (⑧).

---

## 6. What stays local / what is redacted / what is sent

### Allow-listed fields (the only things that leave)

| Field | Example | Purpose |
|---|---|---|
| `payload_id` | `b3f1…` (UUID) | idempotent delivery, dedup |
| `tenant_ref` | `t-acme` | tenant routing (verified against credential) |
| `collector_id` | `col-blr-01` | fleet view |
| `source_id` | `src_9fa2c1` (HMAC pseudonym) | pseudonymous source identity |
| `region` | `in` | residency |
| `event_ts_utc`, `source_tz` | `2026-11-20T09:15:00Z`, `Asia/Kolkata` | ordering, local rendering |
| `window_s` | `5` | aggregation window |
| `metric {name, value, unit}` | `cpu_pct, 91.2, %` | metrics |
| `event {category, severity, count, summary}` | `auth_failure_burst, high, 42, "repeated failed logins"` | security and alert context (summary is template-generated, never copied from raw text) |
| `health_state` | `Fair` | local health verdict |
| `collector_version` | `0.3.1` | fleet view |

### Redacted or dropped (stays local)

| Raw content | Treatment | Example |
|---|---|---|
| Passwords, tokens, API keys, JWTs, private keys | **Scrubbed and dropped** | `password=Hunter2!` → never leaves |
| Usernames, emails | **Dropped** | `user=alice@corp.com` → counted only |
| IPs, hostnames | **Pseudonymized** (HMAC with a local secret) | `10.2.4.7` → `src_9fa2c1` |
| Raw log lines, request/response payloads | **Never sent**; replaced by counts and categories | 42 lines → `count: 42` |
| Free-text messages | **Replaced** with a template summary | no raw string reaches the payload |

**Two independent gates:** the regex/entropy scrubber, and a strict allow-list schema (`extra="forbid"`). Even if the scrubber misses a secret, it cannot leave, because free text has no field to travel in.

### Who can see what

| Role | Raw logs (local) | Egress log | SaaS metadata | Other tenants' data |
|---|---|---|---|---|
| Customer operator (collector UI) | yes | yes | own tenant | never |
| Customer SaaS user | no | no | own tenant | never |
| Platform operator (us) | no | no | no direct access to tenant data in the demo | never |

**Tenant separation:** `tenant_id` is taken from the authenticated collector credential, never from the payload. Every query is scoped by it, with one datastore per tenant, pinned to the tenant's region.

---

## 7. Prioritized features and minimum viable demo

| Priority | Feature | Why it matters |
|---|---|---|
| **P0 (MVP)** | Simulator + collector ingest, redaction, allow-list policy | core privacy claim |
| **P0** | Egress proof panel (raw vs. sent) | mandatory item |
| **P0** | SaaS ingest with auth, dedup by payload_id, tenant scoping | core flow |
| **P0** | Dashboard with 4 health states + stale-data downgrade | Phase 3 |
| **P0** | Outbox buffering, retry, resume with sent/received ID counts | Phase 3, 10 marks |
| **P0** | Proof-metrics view (p95 latency, alert time, offline time) | mandatory item |
| **P1** | Baseline anomaly detection with explanation | Phase 4, weighted higher |
| **P1** | Failed-login local detection and risk indicator | live scenario |
| **P1** | Correlation into incidents + recommendation | live scenario |
| **P2** | Remediation simulation (policy, approve, audit, rollback) | bonus |
| **P2** | Two regions + second tenant, out-of-order demo | Phase 2 / bonus |
| **P3** | Pluggable adapters (syslog, file tail) | when the organizer format is known |

**Minimum viable demo:** stream → collector redaction → egress panel → SaaS ingest with dedup → four health states → one explained anomaly → outage buffer-and-replay with sent/received IDs → proof metrics.

---

## 8. Global concerns (awareness from day one)

- **Regions:** collectors send to their assigned regional endpoint (demo: `in` and `eu`).
- **Residency:** each tenant's metadata is stored only in its chosen region.
- **Time:** all events carry UTC plus the source timezone; dashboards render in the viewer's zone.
- **Ordering:** late events are placed by event time, not arrival time.
- **Idempotency:** every payload has a unique ID, so retries after an outage never create duplicates.

---

## 9. 24-hour plan, roles, and simulated telemetry

### Roles (2–3 coders; merge C into A/B with two people)

| Role | Owns |
|---|---|
| **A — Collector & security** | adapters, redaction, schema/policy, outbox, sender, TLS/HMAC, egress panel |
| **B — SaaS & AIOps** | ingest, dedup, tenant store, health engine, anomaly, correlation, recommendations, proof metrics |
| **C — Dashboard & demo** | React dashboard, simulator and scenario injectors, docs, pitch |

### Simulated telemetry plan
- The organizer's shared stream is the primary input. Until its format is published, our **simulator** produces comparable data: metrics (CPU, memory, disk, latency, packet loss, bandwidth), auth log lines (some containing secrets), and heartbeats.
- A **pluggable adapter layer** (HTTP JSONL, syslog UDP, file tail) lets us switch to the organizer format by writing one small adapter.
- **Scenario injectors** reproduce the judges' live scenarios on demand: secret in log, SaaS outage, failed-login burst, latency spike, CPU drift, alert storm, duplicate/out-of-order delivery.

### Timeline

| Hours | Milestone |
|---|---|
| 0–2 | This Phase 1 pack, repo scaffold, frozen payload schema |
| 2–5 | Architecture doc and diagram (Phase 2) |
| 2–10 | MVP pipeline end to end |
| 10–15 | Buffering, heartbeat, egress panel, failed logins, baseline anomaly (Phase 3) |
| 15–19 | Correlation, recommendations, remediation sim, 2 regions |
| 19–24 | Rehearsal, threshold tuning, slides (Phase 4) |

Feature freeze at hour 19.

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| Scope too large | strict P0/P1/P2 order; MVP defined above |
| Organizer stream format unknown | adapter layer plus our own simulator |
| Hard-coded-looking demo | every number comes from the live stream and timestamps; proof-metrics page |
| False alarms on live injection | persistence over several windows plus baseline, tuned in rehearsal |

---

## 10. One-minute pitch (Phase 1 close)

"Customers can't send raw logs to a SaaS without exposing secrets and breaking compliance. We run a local collector that redacts, aggregates and analyzes inside the customer environment, and ships only an allow-listed payload (numbers, timestamps, pseudonymous IDs, health and alert context) over authenticated TLS to a regional, multi-tenant platform. There, AIOps turns that metadata into correlated incidents with explainable recommendations. And you don't have to take our word for it: the egress proof panel shows exactly what left, next to the raw record that stayed."
