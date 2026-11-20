# API Contract (frozen at scaffold; schema version 1.0.0)

Payload shape: [payload.schema.json](payload.schema.json), generated from `collector/schema.py`.
Change process: propose in chat, collector owner edits, SaaS owner approves, merge before anyone codes against it.

Status column: **live** = implemented in the scaffold, **planned** = contract only.

## SaaS (one load-balanced URL, `http://localhost:8080` in compose)

### Collector auth (all `/v1/ingest`, `/v1/heartbeat` calls)
- `X-Collector-Key`: identifies the collector. The SaaS maps it to a tenant and collector id; **the tenant is never taken from the body**.
- `X-Signature`: lowercase hex HMAC-SHA256 of the **raw request body** using the collector's secret.
- Dev compose uses plain HTTP behind the load balancer. Production terminates TLS at the load balancer (mTLS recommended).

### Dashboard auth (all `GET /v1/*`)
- `X-Dashboard-Token`: maps to one tenant. Every query is scoped to that tenant.

| Method and path | Status | Caller | Purpose |
|---|---|---|---|
| `GET /healthz` | live | load balancer | liveness and replica id |
| `POST /v1/ingest` | live | collector | body `{"payloads":[Payload,...]}`; response `{"accepted":[id],"duplicate":[id],"rejected":[{"payload_id":id,"reason":str}]}` |
| `POST /v1/heartbeat` | live | collector | body `{"collector_id","version","ts_utc","config_hash","buffer_depth"}` |
| `GET /v1/fleet` | live | dashboard | collectors with `state`, `state_reason`, `last_seen_utc`, `version`, `buffer_depth` |
| `GET /v1/metrics?source=&name=&from=&to=` | live | dashboard | time series ordered by event time |
| `GET /v1/incidents` | planned | dashboard | correlated incidents with recommendations and explanation |
| `GET /v1/health/history` | planned | dashboard | UTC-timestamped state transitions with reasons |
| `GET /v1/proof` | planned | dashboard | p95 latency, alert delay, offline-detection time, sent vs. received counts |
| `POST /v1/remediation/{id}/approve` | planned | dashboard | simulated approval step |
| `GET /v1/stream` | planned | dashboard | server-sent events |

Idempotency: `(tenant, payload_id)` is a primary key. Re-sending the same payload to any replica returns it under `duplicate`.
Ordering: events are stored and queried by `event_ts_utc`, never by arrival time.
Staleness: a collector with no heartbeat or payload for `STALE_AFTER_S` (default 60) is reported as `Poor`.

## Collector local API (port 8101)

| Method and path | Status | Purpose |
|---|---|---|
| `POST /ingest` | live | raw telemetry, one record per line, **any format** (JSON, syslog, key=value, text) |
| `GET /local/raw` | live | recent raw records with secrets visible (local view only) |
| `GET /local/egress` | live | exact payloads queued or sent, with the redactions applied to the raw record each came from |
| `GET /local/buffer` | live | outbox depth, link state, last send |
| `POST /local/saas-link/{up\|down}` | live | demo switch that simulates a SaaS outage |
