# Signal Labs

**Secure, AIOps-driven observability that keeps raw data where it belongs: inside the customer environment.**

Built for the CICADA 2026 24-hour hackathon (TechForcz x Atria Institute of Technology).
Problem: *End-to-end, secure AIOps observability delivering autonomous insights across enterprise, data center, cloud and distributed architectures.*

> **Status:** planning complete, implementation starting. See [Roadmap](#roadmap).

---

## The idea

Traditional monitoring ships raw logs, payloads and credentials to a central platform. That widens the attack surface and can breach compliance rules.

Signal Labs uses a **two-tier architecture**:

| Tier | Runs in | Does |
|---|---|---|
| **Local Collector** | Customer environment | Collects telemetry, redacts secrets, aggregates, analyzes locally, applies a data policy, and sends only allow-listed metadata. |
| **SaaS Platform** | Central, uniform, highly available, multi-tenant | Ingests metadata only, then runs fleet analytics, AIOps correlation, dashboards, alerts and explainable recommendations. |

An **egress proof panel** shows exactly what each payload contained before it left, next to the raw record that stayed.

```
Sources ─► Collect ─► Redact ─► Aggregate ─► Analyze locally ─► Policy gate ─► Outbox ─► Egress log
                                                                                  │
                                        TLS + API key + HMAC, regional endpoint   ▼
                              SaaS: ingest ─► dedup ─► health ─► AIOps ─► dashboard / incidents / recommendations
```

## Key features

- **Local-first privacy:** secret scrubbing, HMAC pseudonymous source IDs, and a strict allow-list schema that rejects any extra field.
- **Metadata-only SaaS:** tenant ID comes from the authenticated credential, never from the payload; one datastore per tenant, pinned to its region.
- **Any traffic format:** the collector auto-detects and parses JSON, syslog, text, CSV, key=value, SNMP and flow data into one internal model, and batches and compresses what it sends.
- **Highly available, automated, packaged:** stateless SaaS replicas behind a load balancer on shared Postgres; collectors enroll themselves with a one-time token; everything ships as Docker images and starts with one command.
- **Four health states:** Excellent / Good / Fair / Poor, with configurable thresholds, a reason for every transition, and stale-data downgrade.
- **Explainable AIOps:** baselines and anomaly detection beyond static thresholds, correlation of many alerts into one incident, and recommendations that show their contributing signals, confidence and reasoning path.
- **Reliable delivery:** local buffering during outages, retry with backoff, idempotent payload IDs, and out-of-order events placed by event time.
- **Measured performance:** a proof view computes latency, alert delay and offline-detection time from stream timestamps, and compares sent vs. received IDs.
- **Safe remediation (simulated):** policy check, human approval, audit record and rollback plan.

## Real-time targets

| Measure | Target |
|---|---|
| Collection to dashboard | ≤ 10 s (p95) |
| Threshold breach to alert | ≤ 15 s |
| Collector offline to status Poor | ≤ 60 s |
| Post-outage backlog | zero loss, zero duplicates |

## Planned stack

Python 3.11 (FastAPI, Pydantic) · SQLite on the collector, Postgres on the SaaS · nginx or Traefik load balancer · React + Vite · Docker Compose · GitHub Actions CI

## Planned repo layout

```
collector/   any-format parsers, redaction, allow-list schema, aggregation, outbox, sender, enrollment, local UI
saas/        stateless ingest replicas, auth, Postgres tenant store, health engine, AIOps, remediation sim, proof metrics
dashboard/   React + Vite dashboard
simulator/   telemetry generator and live-scenario injectors
docs/        phase documents and diagrams
scripts/     one demo script per live scenario
deploy/      load balancer config, install and enrollment scripts, CI workflow
```

## Documentation

- [starter.md](starter.md): full plan covering what, how, who and when, mapped to the judging criteria.
- [docs/phase1.md](docs/phase1.md): problem understanding, use cases, trust boundary, allow-list and redaction table, MVP and 24-hour plan.

## Roadmap

- [x] Problem analysis and execution plan
- [x] Phase 1 documentation
- [ ] Phase 2: architecture document and diagram
- [ ] Repo scaffold and frozen payload schema
- [ ] MVP pipeline: simulator, collector, SaaS, dashboard
- [ ] Buffering, heartbeat, egress panel, failed-login detection, baseline anomaly
- [ ] Correlation, explainable recommendations, remediation simulation, multi-region
- [ ] Live-scenario rehearsal and final demo

## Honest limitations (planned prototype)

- Remediation is simulated, not executed.
- Self-signed TLS and shared-secret HMAC; production needs mTLS and key management.
- A single Postgres behind the replicas is still one failure point; production needs a replicated database, a message queue and a time-series store.
- Format auto-detection covers a fixed set of formats; unknown formats fall back to generic text parsing.
- Regex-based redaction can miss novel secret formats; production adds entropy detection and review.

## Team

TechForcz x Atria Institute of Technology, CICADA 2026 participants.
