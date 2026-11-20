# Signal Labs — Member B: SaaS and AIOps (HA edition)

This replaces the SQLite prototype. The two FastAPI replicas use one PostgreSQL database. All application data is persisted, not held in process memory. Only `saas/` and `docs/p1/saas-and-aiops.md` belong to Member B. Do not overwrite the team root compose or contracts.

## Quick start (standalone demo on a computer with Docker)

From the repository root, copy `saas/demo.env.example` to `saas/demo.env` and replace the demo credentials before using outside a local sandbox. The standalone compose is for Member B testing, not the team's root compose.

```sh
docker compose --env-file saas/demo.env -f saas/compose.saas.yml up --build -d
docker compose --env-file saas/demo.env -f saas/compose.saas.yml ps
curl http://localhost:8000/healthz
curl http://localhost:8001/healthz
```

Open `http://localhost:8000/docs` for Swagger. `healthz` identifies the replica and checks PostgreSQL. A migration service initializes the schema and a non-superuser application role before either replica starts. The database is not exposed on the host by the standalone compose.

## Run tests

```sh
python -m pip install -r saas/requirements.txt
python -m pytest -q saas/tests
```

Database integration tests require a **dedicated test database** and migrated application credentials. Never set `TEST_DATABASE_URL` to a database containing real tenant data: tests delete records for synthetic tenants t1, t2 and t3. For a disposable standalone demo database, run:

```sh
docker compose --env-file saas/demo.env -f saas/compose.saas.yml exec -e TEST_DATABASE_URL=postgresql://signal_app:local_app_password@postgres:5432/signal saas-1 python -m pytest -q saas/tests
```

Adjust password if changed. Tests cover concurrent delivery to two replicas, direct RLS read/write isolation, same-ID conflicts, late event ordering, health, HMAC, allow-list, correlation, recommendations and proof. The local build environment had no PostgreSQL/psycopg, so only database-independent tests have been executed there.

## Team integration handoff (Member C)

Use build context `./saas`, internal port 8000, `PORT=8000` for both replicas, host ports 8000 and 8001 if needed. `REPLICA_ID=1` or `2`; `REGION=in` for the single central demo; identical `DATABASE_URL` and `SAAS_AUTH_JSON` on both replicas. Use `ADMIN_DATABASE_URL` and `SAAS_DB_PASSWORD` only in the one-time migration job (`python -m saas.migrate`). Never pass admin credentials into the application containers. C owns the load balancer on 8080 and root Compose. Forward `X-Collector-Key`, `X-Signature`, `Authorization`, `Content-Encoding`; preserve exact request bytes for HMAC; disable buffering on SSE; configure upstream health checks/failover. Terminate TLS at the load balancer; use secure connections to the database in production.

## Contract handoff (Member A)

Match `saas/schema.py` to the frozen contract before merging. Request body may be one object or an array of 1–500 objects, up to 1 MiB (including decompressed size). HMAC-SHA256 uses exact transmitted bytes, including compressed bytes when gzip encoding is used. Key is `X-Collector-Key`, signature is `X-Signature` hex (optional `sha256=` prefix). Credentials are mapped to tenant and collector; region and IDs in payload must match. Example auth map (synthetic):

```json
{"collectors":{"c1":{"tenant":"t1","region":"in","collector":"one","secret":"local_secret"}},"dashboard":{"d1":{"tenant":"t1","region":"in","role":"operator"}}}
```

Responses (proposed; send to A for contract freeze):

| Endpoint | Response |
|---|---|
| POST /v1/ingest | `{accepted:[], duplicate:[], conflict:[]}` IDs; altered body under the same ID is a conflict |
| POST /v1/heartbeat | `{accepted:true,server_ts_utc}`; input `{collector_id,collector_version,config_hash,resource_usage}` |
| GET /v1/fleet | array of collectors, reasons, state, last_seen_utc, version, resources, online |
| GET /v1/metrics | array of allow-listed payloads plus received_ts_utc, ordered by event time; source/name/from/to filters |
| GET /v1/incidents | array of incidents, signals, confidence, recommendation |
| GET /v1/health/history | array of state transitions |
| GET /v1/proof | measurement object with unique received IDs, counts, p95 latency and alert/offline delays |
| POST /v1/remediation/{id}/approve | simulated action and rollback record; operator only |
| GET /v1/stream | SSE snapshot every 2 seconds; bearer auth (use fetch streaming, not plain EventSource) |
| POST /v1/proof/render?payload_id=... | extra proposed UI acknowledgement endpoint for real render latency |
| GET /healthz | `{status,region,replica_id}` readiness |

Dashboard authentication uses `Authorization: Bearer <dashboard-token>`. Viewer can read tenant metadata, operator can approve simulation. Enrollment is A's responsibility; current server credential provisioning is static configuration, not dynamic enrollment. Raw logs must never be sent to these endpoints.

## Failover smoke test

1. Start both replicas and send signed metadata to replica 1. Run `python -m saas.demo_client --url http://localhost:8000` from root (uses demo credentials; change env if needed).
2. Run `docker compose --env-file saas/demo.env -f saas/compose.saas.yml stop saas-1`.
3. Re-run the demo client with `--url http://localhost:8001`: the identical ID/body must be duplicate; existing metadata still visible. The team load balancer test should additionally send the same requests via port 8080 throughout failover.
4. Start replica 1 again and check shared state. This validates app-replica failover only, not PostgreSQL failover.

## Limitations and proof requirements

- Shared standalone Postgres is a single point of failure. Production requires replicated database, backup, managed secrets, mTLS/TLS and a connection pool.
- Tenant RLS uses transaction-local context from verified credentials and a nonprivileged DB role; the application remains a trusted boundary, not protection against arbitrary SQL execution under its role. Database operations are serialized per tenant via advisory locks to prevent concurrent lost incident updates. This limits throughput under a single large tenant.
- Regional ingest/residency is a design requirement; single-region central live demo only. Separate regional deployments and routing must be implemented to establish cross-region residency.
- Correlation is same pseudonymous source + event-time window, not proven causal topology. Adaptive baseline uses preceding samples only; late points are ordered and evaluated but historical alerts are not recomputed. Confidence is heuristic.
- Dashboard-render acknowledgement and collector sent/received comparison must be integrated by C/A. Missing measurements are null, not invented. Latency and actual live failover goals are unverified until measured.
- Current strict schema blocks extra fields and obvious unsafe summaries, but cannot guarantee arbitrary allowed strings contain no secret. A must generate template summaries and pseudonyms; never forward source text.
- Development credentials are illustrative and intentionally unsuitable for production. Do not commit real credentials or `demo.env`.
