> Historical Phase 1 planning document. Packaging and ownership have changed; use `README.md` for the native run instructions and `docs/phase-2.md` for the current team split. Earlier load-balancer and packaging ideas below are historical proposals, not available run commands.

# CICADA 2026 — Secure AIOps Observability: Starter Guide

> 24-hour hackathon · TechForcz x Atria Institute of Technology
> Problem: *End-to-end, secure AIOps observability delivering autonomous insights across enterprise, data center, cloud and distributed architectures.*

**Key judge question we must answer live:**
*"Show exactly what your local collector sends to SaaS, prove that sensitive and raw data stays in the customer environment, and show how AIOps turns metadata into an actionable recommendation."*

---

## 1. WHAT we are building

A **two-tier** observability platform:

| Tier | Runs where | Responsibility |
|---|---|---|
| **Tier 1 — Local Collector** | Customer environment | Collect → filter/redact → aggregate → analyze locally → apply data policy → send. Raw logs, payloads and secrets **never leave**. |
| **Tier 2 — SaaS Platform** | Central, uniform, highly available, multi-tenant | Metadata-only ingest → fleet analytics → AIOps correlation → dashboards, alerts, recommendations. |

The link is authenticated and encrypted (TLS + API key + HMAC), sent to one central, load-balanced ingest endpoint (regional endpoints stay a documented design option).

### Mandatory (every team — missing any is a serious loss)
1. **Real-time targets measured from timestamps**
   - Event → dashboard ≤ **10 s** (p95)
   - Threshold breach → alert ≤ **15 s**
   - Collector offline → status Poor ≤ **60 s** after last heartbeat
   - Post-outage backlog: **zero loss, zero duplicates** (sent IDs == received IDs)
2. **Organizer-provided simulated telemetry stream** (same for all teams)
3. **Egress proof panel** — visible log of exactly what each payload contained before leaving

### Scoring (100) — "score only what is demonstrated live"
| Phase | Marks | Win condition |
|---|---|---|
| 1. Problem Understanding & Ideation | 10 | Precise "what leaves", small use-case set, believable 24 h plan, Q1/Q2 answers |
| 2. Architecture & Technical Design | 25 | Diagram with every hop labeled, payload schema, outage/dedup design, tenant isolation |
| 3. Implementation & Working Prototype | **35** | Live side-by-side raw vs. redacted, forced outage, measured latency (10 of 35) |
| 4. Final Demo & Presentation | 30 | Live injected scenarios, **explainable AIOps (weighted higher)**, honest limitations |

Bonus (tie-breakers only): privacy pipeline · local buffering · explainable AIOps · alert-noise reduction · safe remediation · global-ready delivery.

---

### Organizer clarifications (these override earlier assumptions)

> "SaaS can be uniform, central and high availability. Traffic format can be anything, to have accurate data and optimization. Build a secure, automated, packaged system which will want to observe everything."

| Organizer note | What we do |
|---|---|
| **Uniform, central, highly available SaaS** | One central SaaS: 2+ stateless replicas behind a load balancer, shared Postgres, idempotency enforced by a database unique constraint on `payload_id`. Demo: kill one replica; collectors keep delivering with zero loss and zero duplicates. Regional ingest and residency stay in the design answer (the guide still asks for them) but are not the live demo. |
| **Traffic format can be anything** | The collector auto-detects and parses JSON, syslog, plain text, CSV, key=value, SNMP and flow data, then normalizes everything to one internal model before redaction. Batching and gzip compression optimize what is sent. |
| **Secure** | TLS, per-collector API key, HMAC-signed payloads, allow-list schema, scrubbing. |
| **Automated** | One-time enrollment token: a new collector registers itself, receives its key and config, and starts reporting with no manual setup. CI builds and tests on every push. |
| **Packaged** | Native local setup is documented in the README. A one-command start and installer remain planned. |
| **Observe everything** | Wide coverage through one parser plugin per source type: infrastructure, network, applications, security. |

---

## 2. Phase 1 talking points (have ready)

- **Q1 — Before observability:** raw logs and credentials shipped to a central tool (exposure + compliance risk), noisy duplicate static-threshold alerts, no consolidated multi-site view, outages discovered by users.
- **Q2 — What we now observe:** per-tenant health (Excellent/Good/Fair/Poor), correlated incidents with likely cause, collector fleet status, and an egress proof showing nothing sensitive left.
- **Use cases:** infra health (CPU/mem/disk), network latency & packet loss, repeated failed logins, collector fleet health.
- **Trust boundary:** everything inside Tier 1 is raw-capable; only the allow-listed payload crosses.
- **Global concerns:** regional ingest, tenant residency, UTC + source tz, out-of-order, idempotency.

---

## 3. HOW — Architecture

```
[Organizer stream / our simulator]
      │ any format: JSON · syslog · text · CSV · key=value · SNMP · flow (auto-detect → parse → normalize)
┌─────────── TIER 1: COLLECTOR ───────────────────────────────────────────┐
│ ingest → raw store (SQLite, TTL retention, LOCAL ONLY)                  │
│ → redact (regex secret scrubber + HMAC pseudonymous IDs)                │
│ → aggregate (5 s windows) → local analysis (failed-login counter, etc.) │
│ → policy (Pydantic allow-list, extra="forbid")                          │
│ → outbox (SQLite, payload_id UUID) → egress log → sender                │
│ Local UI: raw logs (with secrets) | egress proof panel | buffer status  │
└─────────────────────────────────────────────────────────────────────────┘
      │ HTTPS/TLS + per-collector API key + HMAC body signature
      │ retry w/ exponential backoff · heartbeat every 10 s
┌─────────── TIER 2: SaaS (multi-tenant, metadata-only) ──────────────────┐
│ /v1/ingest: verify signature → tenant from credential (never payload)   │
│ → dedup (UNIQUE payload_id) → store ordered by event_ts_utc             │
│ → health engine (4 states, YAML thresholds, stale-data downgrade)       │
│ → AIOps: EWMA baseline + robust z-score, correlation → incidents,       │
│   explainable recommendations (signals, confidence, reasoning path)     │
│ → remediation simulator: policy check → approve → audit → rollback      │
│ → proof metrics: p95 latency, spike→alert, heartbeat→Poor, sent vs recv │
└─────────────────────────────────────────────────────────────────────────┘
      │ REST + SSE/WebSocket
[React dashboard]
```

**High availability:** 2+ stateless SaaS replicas behind a load balancer, one shared Postgres, collectors always talk to the single load-balanced URL. Killing a replica must not lose or duplicate data.
**Regions (design only):** a tenant can be pinned to a region and its data kept there; we document this and show UTC handling, but the live demo uses the single central SaaS.
**Tenant isolation:** `tenant_id` derived from the authenticated credential and enforced in every query; Postgres row-level security by tenant (schema-per-tenant as an upgrade path).

### Allow-listed egress payload (single source of truth: `collector/schema.py`)
```
payload_id, tenant_ref, collector_id, source_id (HMAC pseudonym), region,
event_ts_utc, source_tz, window_s,
metric{name,value,unit} | event{category,severity,count,summary},
health_state, collector_version
```
Anything else is rejected before the outbox. **Dropped/redacted:** raw messages, usernames, IPs/hostnames (pseudonymized), passwords, tokens, API keys, JWTs, emails, payload bodies.

### Four health states (configurable in `thresholds.yaml`)
| State | Meaning | Example rule |
|---|---|---|
| Excellent | Healthy | Reporting, all metrics within baseline |
| Good | Normal | Minor deviation, no service impact |
| Fair | Needs attention | Elevated latency/CPU/packet loss, recurring warnings |
| Poor | Critical | Collector offline, severe degradation, critical security event |

Stale/missing data **downgrades** the state; every transition is UTC-timestamped with a reason in the event history.

### AIOps approach (explainability is weighted higher)
- **Detect:** EWMA baseline + robust z-score (median/MAD) per metric — not static thresholds only.
- **Correlate:** group alerts by time window + source/service into one incident; report "N alerts → 1 incident".
- **Recommend:** rule-based, each showing contributing signals, baseline used, confidence and reasoning path.
- **Act (simulated only):** policy check → human approval → audit record → rollback plan.

---

## 4. Repo layout

```
cicada/
├─ collector/   parsers/ (any format) adapters/ redact.py schema.py aggregate.py local_analysis.py outbox.py sender.py enroll.py ui/
├─ saas/        ingest.py auth.py store.py health.py aiops/{baseline,anomaly,correlate,recommend}.py
│               remediation.py proof.py config/thresholds.yaml
├─ dashboard/   React + Vite + Recharts
├─ simulator/   stream generator + scenario injectors
├─ docs/        Phase 1 / Phase 2 artifacts, diagrams
├─ scripts/     demo_*.sh (one per live scenario)
├─ deploy/      load balancer config, install + enrollment scripts, CI workflow
├─ scripts/   local run and demonstration scripts (planned)
└─ starter.md
```

**Stack:** Python 3.11 (FastAPI, Pydantic) · SQLite on the collector, Postgres on the SaaS · planned failover proxy · React + Vite · GitHub Actions CI.

---

## 5. WHO — Team roles (2–3 coders)

| Role | Owns |
|---|---|
| **A — Collector & security** | any-format parsers and normalization, redaction, schema/policy, outbox/buffering, batching + compression, sender, TLS/HMAC, enrollment, egress panel, local UI, collector packaging plan |
| **B — SaaS & AIOps** | stateless replicas on Postgres, ingest, DB-enforced dedup, tenant isolation, health engine, anomaly/correlation/recommendations, remediation sim, proof metrics |
| **C — Dashboard & demo** | React views, simulator (multi-format) + scenario scripts, native start plan with 2 replicas and a planned failover proxy, one-command start, CI, Phase 1/2 docs, pitch |

With 2 people, merge C into A/B. **Hour 1: agree and freeze the payload schema + API contract** so work runs in parallel.

---

## 6. WHEN — 24-hour timeline

| Hours | Work | Checkpoint |
|---|---|---|
| 0–2 | Phase 1 pack (Q1/Q2, trust-boundary sketch, allow-list table, MVP, roles); scaffold repo; freeze schema | **Phase 1** |
| 2–5 | Architecture diagram (all hops labeled), payload schema doc, outage/dedup + tenant-isolation design, scaling notes | **Phase 2** |
| 2–10 | MVP pipeline: simulator → collector → outbox → SaaS → dashboard with 4 health states | |
| 10–15 | Buffering/retry/heartbeat/offline detection, egress panel, failed-login detection, baseline anomaly, proof-metrics page | **Phase 3** |
| 15–19 | Correlation, explainable recommendations, remediation sim, multi-tenant + HA (2 SaaS replicas, kill-one demo), out-of-order/dedup demo | |
| 19–22 | Rehearse all live scenarios on organizer stream; tune thresholds to cut false alarms | |
| 22–24 | Slides, Q&A prep, final dry run | **Phase 4** |

**Feature freeze at hour 19.** Plug in the organizer stream adapter as soon as its format is published.

### MVP (must work even if everything else slips)
Stream → collector redaction → egress panel → SaaS ingest with dedup → 4 health states → one explained anomaly → outage buffer-and-replay with sent/received ID counts → proof-metrics numbers.

---

## 7. Live scenarios to rehearse

| # | Scenario | Must show |
|---|---|---|
| 1 | Raw log contains a secret | Redacted/local only; SaaS gets allowed metadata only |
| 2 | Collector loses SaaS | Detect, buffer, retry, resume; sent IDs == received IDs |
| 3 | Repeated failed logins | Local security summary/risk indicator; no raw auth records exported |
| 4 | Network latency rises | Affected source, severity, trend, service impact |
| 5 | CPU/memory deviates from baseline | Anomaly flagged, signals explained, investigate recommendation |
| 6 | Several alerts, one incident | Correlated into a single incident; noise reduced |
| 7 | Duplicate / out-of-order delivery | Ordered by event time, de-duped by payload ID |
| 8 | Remediation proposed | Policy check → approval → audit → rollback |

---

## 8. Evaluation sheet checklist (tick from the running system)

**Phase 1** ☐ why raw stays local ☐ four use cases ☐ prioritized features + MVP ☐ local/redacted/sent + tenant separation ☐ 24 h scope/roles/sim plan ☐ Q1 before ☐ Q2 observation
**Phase 2** ☐ two-tier authenticated ☐ collect→redact→aggregate→analyze→policy→send ☐ allow-list, scrubbing, pseudonyms, auth, TLS, audit ☐ CPU/mem/disk/bandwidth/latency/packet loss ☐ AIOps beyond thresholds, scales ☐ regional ingest, residency, UTC, out-of-order, idempotent
**Phase 3** ☐ collector on organizer stream, raw stays local ☐ SaaS shows allow-listed only, per tenant ☐ 4 health states + thresholds + stale handling ☐ contextual anomaly alerts, outage detection, buffering, retry ☐ egress proof panel ☐ ≤10 s / ≤15 s / ≤60 s, zero loss/duplicates
**Phase 4** ☐ raw → recommendation end-to-end ☐ correct live scenario response, few false alarms ☐ **explainable AIOps** ☐ limitations + innovation ☐ clear presentation
**Mandatory** ☐ timestamps-measured real-time ☐ shared organizer stream ☐ egress proof panel

---

## 9. Innovation angles (pick 1–2)

- **Egress diff view:** raw record vs. sent payload with every removed/pseudonymized field highlighted, plus a hash chain so SaaS can verify the egress log matches what it received.
- **Noise-reduction score:** "N alerts → 1 incident", shown live.
- **Recommendation trace:** signal contribution weights, baseline used, confidence, rule path.

---

## 10. Questions judges will ask — have answers ready

- *What exactly leaves, and what stays?* → the allow-list schema; show the egress panel.
- *How do you stop secrets leaking by accident?* → regex scrubber **plus** `extra="forbid"` allow-list as a second gate; free text never reaches the payload.
- *How are collectors authenticated and data encrypted?* → per-collector API key, HMAC-signed body, TLS.
- *Real anomaly vs. normal spike?* → EWMA/MAD baseline, persistence over several windows, multi-signal agreement.
- *What happens when SaaS is unreachable?* → outbox buffer, exponential-backoff retry, replay with idempotent `payload_id`.
- *How do you scale?* → stateless SaaS replicas behind a load balancer (regional ingest as an extension), queue (Kafka/NATS) in production, time-series store (Timescale/ClickHouse), tenant-sharded storage.
- *Safeguards before automated remediation?* → policy bounds, human approval, audit log, rollback, test-environment-only.

## 11. Honest limitations (state them plainly in Phase 4)

- Remediation is simulated, not executed.
- Self-signed TLS and a shared-secret HMAC; production needs mTLS and a KMS/rotation.
- Single Postgres behind the replicas is still one failure point; production needs a replicated database, a message queue and a time-series store.
- Format auto-detection covers a fixed set of formats; unknown formats fall back to generic text parsing with less accurate fields.
- Regex redaction can miss novel secret formats; production adds entropy detection and DLP review.
- Baselines are simple statistics; no learned models or seasonality yet.

---

## 12. First steps (do these now)

1. Freeze `collector/schema.py` and the API contract; share with the team.
2. Follow the native setup in the README; coordinate the one-command start script with the edge owner.
3. Build the simulator and the thin path: simulator → collector → SaaS → dashboard.
4. In parallel, write the Phase 1 pack in `docs/` (Q1/Q2, trust-boundary sketch, allow-list table).
5. Ask organizers for the stream format and add its adapter as soon as it is known.
