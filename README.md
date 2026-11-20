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
- **Metadata-only SaaS:** tenant ID comes from the authenticated credential, never from the payload; tenant data is isolated by row-level security in Postgres, and each region has its own database.
- **Any traffic format:** the collector auto-detects and parses JSON, syslog, key=value and plain text into one internal model (anything else is read as plain text; SNMP, flow and CSV parsers are not built), and sends in batches of up to 50 payloads (no compression yet).
- **Highly available (replicas on shared Postgres), automated, packaged:** stateless SaaS replicas share one Postgres with row-level tenant isolation. One-time-token enrollment works end to end, on the platform and in the collector. Docker packaging was removed for now; everything runs natively (see Quick start).
- **Four health states:** Excellent / Good / Fair / Poor, with configurable thresholds, a reason for every transition, and stale-data downgrade.
- **Explainable AIOps:** baselines and anomaly detection beyond static thresholds, correlation of many alerts into one incident, and recommendations that show their contributing signals, confidence and reasoning path.
- **Reliable delivery:** local buffering during outages, retry with backoff, idempotent payload IDs, and out-of-order events placed by event time. Zero loss and zero duplicates were shown by comparing payload ID sets through an outage and through killing a replica behind the failover proxy.
- **Egress proof:** a collector-local page (`/local/ui`) shows the raw records that stayed next to the exact payload that left, with a leak check. It answers only requests from the same machine.
- **Secure and bounded:** TLS with a verified, pinned CA; a data policy file that marks every field; retention and size caps so a flood cannot fill the disk (losses are counted and reported); one-time-token enrollment.
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

Python 3.11+ (FastAPI, Pydantic) · SQLite on the collector, PostgreSQL 16+ on the SaaS (row-level security) · React + Vite · GitHub Actions CI

## Planned repo layout

```
collector/   any-format parsers, redaction, allow-list schema, aggregation, outbox, sender, enrollment, local UI
saas/        stateless ingest replicas, auth, Postgres tenant store, health engine, AIOps, remediation sim, proof metrics
dashboard/   React + Vite dashboard
simulator/   telemetry generator and live-scenario injectors
docs/        phase documents and diagrams
scripts/     one demo script per live scenario
```

## Quick start (no Docker)

Needs Windows with Python 3.11+, Node 20+ and PostgreSQL 16+ installed locally (the scripts are PowerShell).

```
pip install -r collector/requirements.txt -r saas/requirements.txt -r scripts/requirements.txt
python -m pytest collector saas -q
```

Run the whole stack with one command (Postgres, migration, two SaaS replicas, the failover proxy, the collector and the dashboard, over TLS with a private dev CA):

```
.\scripts\run-local.ps1 -Tls
.\scripts\demo.ps1 secret          # inject a live scenario; -List shows all 14
.\scripts\stop-local.ps1
```

Then open the dashboard at `http://127.0.0.1:5173` and the collector's egress proof panel at `http://127.0.0.1:8101/local/ui` (this machine only). Everything uses development credentials and a private CA; never reuse them. Full instructions, flags, settings and every scenario are in [scripts/README.md](scripts/README.md).

The database tests in `saas/tests` are skipped unless `TEST_DATABASE_URL` and `TEST_DATABASE_URL_EU` point at dedicated, migrated test databases (see `saas/README.md`); they delete rows for synthetic tenants, so never aim them at real data. The TLS tests skip unless `cryptography` is installed (`pip install -r scripts/requirements.txt`).

The payload contract is in [contracts/](contracts/): `collector/schema.py` is the source, `contracts/payload.schema.json` is generated from it, and a test fails if they drift. Regenerate with `python -m collector.export_schema`.

## Documentation

- [docs/phase-2.md](docs/phase-2.md): where every Phase 2 item stands, with evidence, gaps and task status.
- [docs/p2/collector.md](docs/p2/collector.md) and [docs/p2/trust-boundary.svg](docs/p2/trust-boundary.svg): the collector design, the data flow with every hop labeled, reliability and the evidence map.
- [docs/p2/saas.md](docs/p2/saas.md) and [docs/p2/architecture.md](docs/p2/architecture.md): the platform design, residency, high availability and limits.
- [docs/p1/security-and-data-protection.md](docs/p1/security-and-data-protection.md): what leaves, what stays, the controls and their limits.
- [docs/phase-1.md](docs/phase-1.md) and [docs/phase1.md](docs/phase1.md): the Phase 1 work split and problem understanding.
- [starter.md](starter.md): the original plan, mapped to the judging criteria.
- [scripts/README.md](scripts/README.md): running the stack, scenarios, TLS, retention, enrollment and failover.
- [contracts/](contracts/): the frozen payload schema and the API.

## Roadmap

- [x] Problem analysis and plan; Phase 1 and Phase 2 documentation
- [x] Frozen payload schema and a working pipeline: simulator, collector, SaaS, dashboard
- [x] Collector: local aggregation and failed-login bursts, data policy, real host telemetry, TLS, egress proof panel, retention and limits, enrollment, failover proxy
- [x] Platform: correlation and explainable recommendations, ontology and lineage, simulated actions, contract enforcement, region-bound databases
- [ ] Measure the real-time targets on a clean, steady stream (dashboard 10 s p95, alert 15 s, offline detection 60 s)
- [ ] Record a scale figure with the load tool
- [ ] Integrate the organizer's telemetry stream (its format is not yet known)
- [ ] Live-scenario rehearsal and final demo

## Honest limitations

- Remediation is simulated, not executed.
- TLS uses a private dev CA and authenticates the server only. Production needs client certificates (mTLS), real certificates and key management.
- Postgres and the failover proxy are each a single point of failure. Production needs a replicated database, a message queue and a time-series store.
- Under a flood or a long outage the collector drops its oldest undelivered data by design; every drop is counted and reported.
- Format detection covers JSON, syslog, key=value and plain text; anything else is read as plain text. There is no request compression.
- Scrubbing is pattern-based and can miss novel secret formats. Free text cannot travel in a payload, so a miss is not a leak.
- "Packet loss" is the share of failed TCP connects, not an ICMP measurement.
- The collector's local health verdict is a constant; health is computed on the platform.
- Residency across regions is a design answer: one region runs live.
- No scale or latency figure has been measured cleanly yet.
- Credentials are stored as files and environment values, and the platform keeps collectors' signing secrets in its database. Production needs a secrets manager and encryption.

## Team

TechForcz x Atria Institute of Technology, CICADA 2026 participants.
