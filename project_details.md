# Signal Labs: Project Details

Secure AIOps observability for the CICADA 2026 hackathon. A **collector** runs in the customer's environment, keeps raw data local, and sends only allow-listed metadata to a **multi-tenant SaaS**. The SaaS scores health, detects and explains anomalies, and proposes safe remediations. A dashboard presents it all.

## 1. Architecture

```
 Telemetry sources                     TIER 3: Collector (customer side)                TIER 2: SaaS platform               TIER 1: Dashboard
 (organizer stream,   push/pull/tail   ┌────────────────────────────────┐   HTTPS +    ┌──────────────────────────┐  REST/SSE  ┌──────────────┐
  simulator, syslog,  ───────────────► │ adapters/parsers → raw store    │  HMAC sig   │ FastAPI (2 replicas +    │ ◄───────── │ React + Vite │
  Prometheus, Influx)                  │ → redact → map → aggregate      │ ──────────► │ failover proxy, TLS)     │   Bearer   │ sign-in, RBAC│
                                       │ → policy allow-list → outbox    │             │ → Postgres 17 (RLS)      │   token    │ views        │
                                       │ → sender (retry, heartbeat)     │             │ → AIOps + Gemini         │            └──────────────┘
                                       │ Local UI: raw logs, egress proof│             └──────────────────────────┘
                                       └────────────────────────────────┘
```

- **Two-tier requirement:** frontend (React) + backend (FastAPI) + database (Postgres). The collector is an additional customer-side tier.
- **Trust boundary:** everything left of the HTTPS hop is customer-controlled. Raw messages, usernames, IPs, secrets and bodies never cross it.
- **Ports (local):** dashboard 5173, platform 8000 (through the failover proxy; replicas 8000/8001), collector 8101, Postgres 5433.

## 2. Components

### Collector (`collector/`)
| Stage | Module | What it does |
|---|---|---|
| Ingest | `adapters.py`, `push.py`, `pull.py`, `parsers/` | HTTP push interface (JSON, NDJSON, Prometheus, Influx line, syslog RFC 5424), pull inputs, file tail. The organizer format is unknown, so inputs are pluggable. |
| Raw store | `main.py`, SQLite | Local only, with retention. The local UI shows raw logs, secrets included. |
| Redact | `redact.py` | Scrubs passwords, tokens, API keys, JWTs and emails. Pseudonymizes IDs, IPs and hostnames with HMAC. |
| Map and aggregate | `mapping.py`/`mapping.yaml`, `aggregate.py` | Maps arbitrary fields to a common model and builds windowed metrics and event counts. |
| Local analysis | `local_analysis.py`, `health.py` | Failed-login counting, a local health state and baselines. |
| Policy | `policy.py`/`policy.yaml`, `schema.py` | Pydantic allow-list with `extra=forbid`. A payload with any field outside the list is rejected before the outbox. |
| Outbox and sender | `outbox.py`, `sender.py` | SQLite outbox with a payload UUID. Retries with backoff, replays after an outage, heartbeats every 10 s, HMAC-signed requests. |
| Enrollment | `enroll.py`, `credentials.py` | Single-use enrollment token that issues collector credentials. |
| Local UI | `ui/` | Raw logs, the **egress proof panel** (exactly what was sent), and buffer status. |

**Egress payload fields:** payload id, tenant ref, collector id, pseudonymous source id, region, event timestamp (UTC), source timezone, window, metric or event summary, health state, collector version.

### SaaS platform (`saas/`)
- **Ingest** (`ingest.py`, `auth.py`): verifies the HMAC signature. The **tenant comes from the credential, never from the payload.** Duplicate payload ids are dropped (`UNIQUE`). Data is placed by event time, so out-of-order arrival is handled.
- **Storage** (`store.py`, `migrations/001-004.sql`): Postgres 17 with **row-level security** per tenant.
- **Health engine** (`health.py`, `config/`): four states (Good, Fair, Poor, Offline) from YAML thresholds. A missed heartbeat downgrades the state.
- **AIOps** (`aiops.py`, `correlation.py`, `forecast.py`):
  - A rolling median/MAD baseline with robust z-scores finds anomalies, with a persistence filter.
  - Correlation groups many signals and alerts into one incident (the alert-noise reduction score).
  - Rule-based recommendations carry the signals, the confidence and the reasoning, so they are explainable.
  - Forecast and what-if endpoints are also available.
- **LLM** (`llm.py`): Gemini (`gemini-3.1-flash-lite`, with fallbacks) writes incident summaries from metadata only. It has a rate limit, an 8 s per-attempt timeout and a 20 s cap. The key lives only in git-ignored `data/gemini.key`.
- **Safe remediation** (`remediation.py`, `actions.py`): propose, then policy check, then human approval, then audit, with rollback. Actions are simulated.
- **Proof** (`proof.py`): measures p95 event-to-render, spike-to-alert and heartbeat-to-Poor from timestamps, plus sent versus received counts.
- **Lineage and ontology** (`ontology.py`): trace an incident or payload back to its sources.

### Dashboard (`dashboard/`)
React + Vite. Fleet and health, incidents with AI summaries and recommendations, noise reduction, forecast and what-if, actions and approvals, audit log, user management, and the proof metrics. It updates live over SSE (`/v1/stream`). Vite proxies `/api` to the platform.

## 3. Security

- **Data protection:** local raw data; redaction and pseudonymization; allow-list enforced by the schema; the egress panel shows the exact bytes sent.
- **Secure communication:** TLS with a private dev CA, per-collector key plus HMAC-signed bodies, and 1-hour signed session tokens (`sl1.`).
- **Access control** (`rbac.py`, `users.py`):
  - **Roles:** viewer, auditor, operator, admin.
  - **Permissions:** read, audit.read, ai.summary, action.propose, action.decide, enrollment.create, users.manage. Every dashboard route calls `need(request, permission)`.
  - **Accounts:** scrypt-hashed passwords, a 5-failures-in-5-minutes lockout, and a guard that keeps the last admin.
  - **Tokens and audit:** the role is read from the database on each request, not from the token. Refused requests are audited with the actor.
- **Tenant isolation:** the tenant comes from the credential, and Postgres row-level security backs it up.
- **Public mode** (`run-local.ps1 -Public`):
  - Random collector secrets in git-ignored `data/public.json`, and static API tokens switched off (`SAAS_DISABLE_API_TOKENS=1`).
  - The built dashboard is served, and `/api/v1/(ingest|heartbeat|enroll|enrollment-tokens)` return 403 on the public address.

## 4. Data flow

1. A source sends telemetry to the collector (push, pull or tail). The raw record is stored locally.
2. The collector redacts, maps and aggregates it into a window.
3. The policy allow-list validates the payload, and it enters the outbox with a UUID. The egress log records it.
4. The sender posts it over HTTPS with an HMAC signature. If the platform is down, it retries with backoff and replays from the outbox afterwards. Heartbeats run every 10 s.
5. The platform verifies the signature, takes the tenant from the credential, and drops duplicates. It stores the payload by event time and updates health.
6. AIOps scores deviations, correlates them into incidents and recommends actions. Gemini adds a metadata-only summary.
7. The dashboard reads over REST and SSE, as a signed-in user whose role limits what they can see and do.
8. The proof engine compares timestamps at each hop to produce the latency numbers, and compares sent with received ids.

## 5. API (main routes, `saas/main.py`)
- **Collector:** `POST /v1/ingest`, `/v1/heartbeat`, `/v1/enroll`, `/v1/enrollment-tokens`
- **Auth and users:** `/v1/login`, `/v1/logout`, `/v1/session`, `/v1/me/password`, `/v1/users`, `/v1/rbac`
- **Data:** `/v1/fleet`, `/v1/metrics`, `/v1/incidents`, `/v1/health/history`, `/v1/health/thresholds`, `/v1/noise`, `/v1/forecast`, `/v1/what-if`, `/v1/ontology`, `/v1/objects/...`, `/v1/lineage/...`, `/v1/audit`
- **AI and actions:** `/v1/ai/status`, `/v1/incidents/{id}/ai-summary`, `/v1/actions`, `/v1/actions/propose`, `/v1/actions/{id}/{operation}`, `/v1/remediation/{id}/approve`
- **Proof and stream:** `/v1/proof`, `/v1/proof/render`, `/v1/system/status`, `/v1/stream`, `/healthz`

## 6. Repository layout
```
collector/   customer-side agent          saas/        platform (API, AIOps, RBAC, migrations)
dashboard/   React + Vite UI              simulator/   data generator, scenarios, measurement tools
scripts/     run-local, reset-demo, go-public, demo, rehearse, recover, bundle-evidence
contracts/   shared schemas               docs/        phase 1-4 documents and evidence
```

## 7. Running it
- **Stack:** `.\scripts\run-local.ps1` (set `$env:PYTHON` to a Python with the dependencies installed).
- **Clean demo:** `.\scripts\reset-demo.ps1`. Wait about 2 minutes for the simulator baseline.
- **Public:** `.\scripts\go-public.ps1` (reset in public mode plus an SSH tunnel). `-Stop` closes the tunnel.
- **Scenarios:** `.\scripts\demo.ps1 <scenario>`, for example `failed-logins`.
- **Evidence:** `.\scripts\bundle-evidence.ps1`.
- **Sign-in:** organization `t-acme`. Accounts are in `data\dev-users.txt`.

## 8. Known limits
- Remediation actions are simulated.
- The organizer stream is not connected yet. The push interface is ready.
- The public tunnel link rotates and depends on this laptop being on and online.
- The AI engine needs internet access.
- Accounts can be locked by repeated wrong passwords. In public mode, only the dashboard is exposed.
- Details are in `docs/p4/security.md`, `limits-and-definitions.md` and `scale-and-production.md`.
