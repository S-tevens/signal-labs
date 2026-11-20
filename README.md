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
- **Highly available (replicas on shared Postgres), automated, packaged:** stateless SaaS replicas share one Postgres with row-level tenant isolation. One-time-token enrollment is planned. Docker packaging was removed for now; everything runs natively (see Quick start).
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

Needs Python 3.11+, Node 20+ and PostgreSQL 16+ installed locally.

```
pip install -r collector/requirements.txt -r saas/requirements.txt
python -m pytest collector saas -q
```

Database tests in `saas/tests` are skipped unless `TEST_DATABASE_URL` points at a dedicated, migrated test database (see `saas/README.md`).

**1. A local Postgres (one time, port 5433, PowerShell):**

```
$pg = "C:\Program Files\PostgreSQLin"
& "$pg\initdb.exe" -D data\pg -U postgres --auth=trust -E UTF8
& "$pg\pg_ctl.exe" -D data\pg -o "-p 5433" -l data\pg.log start
& "$pg\createdb.exe" -h localhost -p 5433 -U postgres signal
$env:ADMIN_DATABASE_URL = "postgresql://postgres@localhost:5433/signal"; $env:SAAS_DB_PASSWORD = "dev_app_password"
python -m saas.migrate
```

**2. Two SaaS replicas, one terminal each** (dev credentials, never reuse them):

```
$env:DATABASE_URL = "postgresql://signal_app:dev_app_password@localhost:5433/signal"
$env:REGION = "in"
$env:SAAS_AUTH_JSON = '{"collectors":{"key-acme-1":{"tenant":"t-acme","region":"in","collector":"col-blr-01","secret":"dev-secret-acme"}},"dashboard":{"dash-acme":{"tenant":"t-acme","region":"in","role":"operator"}}}'
$env:REPLICA_ID = "1"; python -m uvicorn saas.main:app --port 8000
# second terminal: same variables, $env:REPLICA_ID = "2", --port 8001
```

**3. Collector, simulator, dashboard:**

```
$env:SAAS_URL = "http://127.0.0.1:8000"; python -m uvicorn collector.main:app --port 8101
python simulator/generator.py --scenario secret
python simulator/generator.py --seconds 60
cd dashboard; npm install; npm run dev
```

Look at `http://localhost:8101/local/raw` (secrets visible, local only) and `http://localhost:8101/local/egress` (exactly what left). Read the SaaS side with `Authorization: Bearer dash-acme` on `http://localhost:8001/v1/fleet` or `/v1/proof` (replica 2 reads what replica 1 stored). Simulate an outage with `curl -X POST localhost:8101/local/saas-link/down` (and `/up` to reconnect).

There is no load balancer now, so the collector talks to one replica; stopping that replica makes it buffer and retry. The dashboard still shows demo data and is not connected to the SaaS yet.

The payload contract is in [contracts/](contracts/): `collector/schema.py` is the source, `contracts/payload.schema.json` is generated from it, and a test fails if they drift. Regenerate with `python -m collector.export_schema`.

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
