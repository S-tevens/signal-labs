# Scale and production note

This records one measured run on a development machine and, separately, proposals for production. Only the first section was measured.

## Measured (one run, 2026-11-21)

Command: `SAAS_URL=https://127.0.0.1:8080 SAAS_CA_FILE=data/certs/ca.pem python simulator/throughput.py`

| Measure | Result |
|---|---|
| SaaS ingest, payloads accepted | 10000 of 10000 sent |
| Failed requests | 0 (20 requests of 500 payloads) |
| SaaS throughput, end to end | about 196 payloads/second (51.1 s) |
| Request latency per 500-payload batch, p50 / p95 | 2638 ms / 3494 ms |
| Spot check via `GET /v1/objects/observation/<id>` | 20 of 20 random sent IDs found |
| Collector intake | about 1017 lines/second (20000 lines in 19.7 s) |
| Collector `/local/stages` delta | received 20053, aggregated 20053 (20000 sent by the test) |

### Method

- SaaS: 10000 valid payloads for tenant `t-acme`, collector `col-blr-01`, key `key-acme-1`, each with a unique uuid `payload_id` and a distinct `event_ts_utc` in the past. 50 distinct `source_id` values. Constant `cpu_pct` of 30.0 so no alerts fire. Sent as HMAC-signed batches of 500 over HTTPS through the entry point on port 8080, one request at a time. Throughput is payloads divided by total wall time, including signing and JSON encoding on the client.
- Collector: 20000 `ts=<iso> host=<h> metric=cpu_pct value=30` lines posted to `/ingest` in chunks of 2000, one request at a time. The stage counters were read before and after.
- The 53 extra received lines are from other live traffic on the running stack, not from the test.

### Caveats

- One machine runs the client, collector, SaaS and database together, so they compete for the same CPU.
- Loopback only: no network latency, no TLS to a distant client, no packet loss.
- A development Postgres with default settings, not tuned or replicated.
- Simulator data with one tenant, one collector and constant values.
- A single run: no repeats, no variance, no warm-up separation.
- Sequential clients: concurrency was 1, so this is not a saturation or peak figure.

These numbers are a local baseline. They say nothing about global scale, and global scale was not measured.

## What would change for production

These are proposals only. None is implemented here, and none has been measured.

- A queue between ingest and storage, so the ingest endpoint acknowledges quickly and storage writes are absorbed and retried at their own pace.
- A time-series store for metrics, instead of general-purpose tables, for compression and fast range queries.
- Regional replicas and routing, so collectors send to a nearby region and tenant data stays in its permitted region.
- mTLS between collectors and the SaaS, or short-lived rotated tokens in place of long-lived shared keys.
- Autoscaling replicas of the ingest service based on request rate or queue depth.
- Retention tiers: recent data at full resolution, older data downsampled or moved to cheaper storage, then deleted on a per-tenant schedule.
