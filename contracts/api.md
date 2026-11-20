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
| `POST /v1/remediation/{id}/approve` | simulated approval with rollback record (operator only) |
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
