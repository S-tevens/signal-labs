# API Contract (frozen at scaffold; schema version 1.0.0)

Payload shape: [payload.schema.json](payload.schema.json), generated from `collector/schema.py`.
Change process: propose in chat, collector owner edits, SaaS owner approves, merge before anyone codes against it.

Status column: **live** = implemented in the scaffold, **planned** = contract only.

## SaaS (replicas share one Postgres; `http://localhost:8000` and `:8001` locally)

The live SaaS is `saas/` (see `saas/README.md`); this section records the agreed shapes.

### Collector auth (`/v1/ingest`, `/v1/heartbeat`)
- `X-Collector-Key`: identifies the collector. The SaaS maps it to a tenant, region and collector id; **identity is never taken from the body**, and a payload whose `tenant_ref`, `collector_id` or `region` does not match the credential is refused (403).
- `X-Signature`: lowercase hex HMAC-SHA256 of the **exact request bytes** (optional `sha256=` prefix).
- Body is one payload or a **JSON array of 1-500 payloads**, up to 1 MiB. `Content-Encoding: gzip` is accepted; the HMAC covers the transmitted bytes.
- Local dev uses plain HTTP and talks to one replica directly. Production terminates TLS at a load balancer in front of the replicas (mTLS recommended).

### Dashboard auth (all `GET /v1/*`, `/v1/stream`)
- `Authorization: Bearer <dashboard-token>`, bound to one tenant and a role (`viewer` reads, `operator` may approve the simulated remediation).

| Method and path | Purpose |
|---|---|
| `GET /healthz` | readiness: `{status, region, replica_id}`; checks the database |
| `POST /v1/ingest` | response `{"accepted":[id],"duplicate":[id],"conflict":[id]}`; the same ID with a different body is a `conflict` |
| `POST /v1/heartbeat` | body `{collector_id, collector_version, config_hash, resource_usage}`; response `{accepted, server_ts_utc}` |
| `GET /v1/fleet` | collectors with state, reasons, last seen, version, resources |
| `GET /v1/metrics?source=&name=&from=&to=` | allow-listed payloads ordered by event time |
| `GET /v1/incidents` | correlated incidents with signals, confidence and recommendation |
| `GET /v1/health/history` | UTC-timestamped state transitions with reasons |
| `GET /v1/proof` | measured latency, alert and offline delays, unique received IDs and counts |
| `POST /v1/proof/render?payload_id=` | UI acknowledgement so real render latency can be measured |
| `POST /v1/remediation/{id}/approve` | deprecated: returns 410; use the actions proposal lifecycle below |
| `GET /v1/stream` | server-sent events, a snapshot every 2 seconds |

Idempotency: a payload ID is unique per tenant; re-sending it to any replica returns it under `duplicate`.
Ordering: events are stored and queried by `event_ts_utc`, never by arrival time.
Staleness: a collector that stops reporting is downgraded, not shown at its last good state.

## Collector local API (port 8101)

| Method and path | Status | Purpose |
|---|---|---|
| `POST /ingest` | live | raw telemetry, one record per line, **any format** (JSON, syslog, key=value, text) |
| `GET /local/raw` | live | recent raw records with secrets visible (local view only) |
| `GET /local/egress` | live | exact payloads queued or sent, with the redactions applied to the raw record each came from |
| `GET /local/buffer` | live | outbox depth, link state, last send |
| `POST /local/saas-link/{up\|down}` | live | demo switch that simulates a SaaS outage |

## Phase 2 platform APIs

All object, lineage, action, noise, and history reads require the dashboard bearer token. RLS applies the tenant from that authenticated token; cross-tenant IDs return 404. No collector-local raw records or redactions are exposed through SaaS. Object IDs must be URL encoded. Results are bounded to 500 list items unless otherwise stated.

- `GET /v1/ontology` returns `{types, links, boundary}`. Property classifications describe SaaS metadata; they do not enforce the collector's local policy.
- `GET /v1/objects/{type}` returns an array of `{type,id,properties,links}`. Types: `tenant`, `collector`, `source`, `observation`, `incident`, `recommendation`, `action`.
- `GET /v1/objects/{type}/{id}` returns the object with linked IDs. A recommendation uses its incident ID. An observation ID is a `payload_id`. Incident evidence contains only the signals retained in the incident; the correlation engine retains at most 100.
- `GET /v1/lineage/incident/{id}` returns `{incident_id,collector_id,source_id,signals,payload_ids,recommendation,note}`.
- `GET /v1/lineage/payload/{id}` returns `{payload_id,collector_id,source_id,incidents,note}`. Reverse lookup searches the retained incident signals; it is not a complete long-term lineage archive.
- `GET /v1/noise` returns `{alerts,incidents,reduction_ratio,scope}`; it compares correlated alert counts to retained incidents, not every raw operational event.
- `GET /v1/actions[?incident_id=…]` returns `{types,actions}`. `GET /v1/actions/{id}` includes ordered `audit` entries.
- `POST /v1/actions/propose` accepts `{incident_id,action_type,parameters}`. Types and exact parameters: `restart_service` `{service}`, `isolate_source` `{source_id}`, `rotate_credentials` `{credential_ref}`, `scale_capacity` `{service,replicas}`. Replicas must be an integer 1–20; isolate source must match the incident. Identifiers are limited to safe characters; never submit credentials as parameters.
- `POST /v1/actions/{id}/{approve|reject|rollback}` applies only `proposed → approved`, `proposed → rejected`, or `approved → rolled_back`. Viewer roles may read; operator/admin roles may propose and transition. A 409 means the transition is invalid. Every action is simulated, records an audit entry and rollback plan, and does not execute infrastructure changes. Audit records the role, not a unique human identity.
- The legacy `POST /v1/remediation/{id}/approve` returns 410; use the proposal lifecycle.
- `GET /v1/proof?window_s=300` optionally bounds measurements by receipt/render/offline-measurement time (60–86400 seconds). Response includes `window_start_utc`/`window_end_utc`; duplicate attempts remain cumulative. Sent/missing IDs remain unknown until the collector provides evidence. Client acknowledgement and unsynchronized clocks limit precision.

### Enrollment

`POST /v1/enrollment-tokens` requires an **admin** dashboard credential and body `{collector_id,expires_in_s?}` (60–3600 seconds; default 900). The response gives `{tenant_ref,collector_id,region,token,expires_at}` once, with `Cache-Control: no-store`.

`POST /v1/enroll` accepts `{tenant_ref,token}` at the matching regional endpoint, returning `{tenant_ref,collector_id,region,collector_key,collector_secret,note}` once with `Cache-Control: no-store`. The token is spent atomically. The collector uses the returned key and secret in the existing HMAC headers, so ingest and heartbeat shapes do not change. The key contains an untrusted tenant hint for RLS lookup; authentication and identity come from the stored credential, not payload fields. This prototype stores the HMAC secret in the tenant-scoped database because verification requires it; production needs encrypted secrets, rotation/revocation, rate limiting, and TLS. The edge owner still needs to implement the collector enrollment client. Do not use real credentials over the current plain-HTTP local setup.

### Frozen contract validation

SaaS checks `contracts/payload.schema.json` before Pydantic validation and rejects extra fields or values forbidden by the schema. It also enforces non-null exactly-one bodies, valid IANA timezone, matching metric/unit pairs, UTC, finite numbers, and additional secret screening. Some of these semantic checks are intentionally stricter than the generated JSON Schema. The collector owner retains ownership of the contract and schema.
