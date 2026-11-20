# Phase 1 — SaaS & AIOps (Member B)

## Goal and trust boundary
Signal Labs receives only approved telemetry metadata from the customer's collector. Raw logs, credentials, payloads, usernames and source IP addresses remain local. The collector is responsible for template-generated summaries and source pseudonyms; the SaaS validates the metadata allow-list again and rejects unknown fields. No SaaS API accepts raw telemetry.

```
Customer collector (Member A) -- HTTPS + HMAC, metadata only --> Load balancer :8080 (Member C)
                                                                   |          |
                                                          SaaS replica 1   SaaS replica 2
                                                             :8000            :8001 (host)
                                                                   \        /
                                                               Shared PostgreSQL :5432
                                                                      |
                                                              Dashboard (Member C)
```

## Authentication and tenant isolation
A collector sends `X-Collector-Key` and `X-Signature` (HMAC-SHA256 of the exact transmitted bytes). The server maps the credential to tenant, collector and assigned region. Payload identity fields must match. Dashboard bearer tokens map to a tenant and viewer/operator role. Every database table has tenant_id; PostgreSQL RLS uses transaction-local tenant context set after authentication. Application roles are non-superuser and cannot bypass RLS. RLS is forced on each table; both reads and writes are restricted. An operator can approve remediation simulations only for their own tenant. The SaaS has no raw-log access. The local egress panel is owned by the collector.

## Central HA and delivery
Two interchangeable stateless FastAPI replicas use one PostgreSQL database. Events, baselines (persisted metric history), fleet, incidents, counters, approval audit and proof data are shared. `REPLICA_ID` identifies the serving instance. The load balancer (C) routes around a failed replica. The `(tenant_id, payload_id)` primary key and atomic insert-on-conflict enforce idempotency across replicas. Identical retries return duplicate; altered content with the same ID is a conflict. Transaction-level tenant advisory locks protect read/modify/write incident and fleet operations. The collector owns durable buffering and retries; SaaS acknowledges IDs only after a successful DB transaction. A database outage still affects both replicas; production database HA is future work.

## Global-ready design
The demonstration uses a single central region (`in`) with two replicas as specified in the updated team plan. In production, authenticated collectors use a region-specific endpoint and tenant-assigned data stores; the region is checked against credentials and payloads. Residency requires independently deployed regional databases and explicit approved cross-region replication policies. UTC is mandatory for the event timestamp; IANA source timezone travels separately. Normalized timestamps sort lexicographically in event-time order. Late metrics remain queryable in correct order and use earlier observations for their anomaly baseline. The latest state of a signal cannot be overwritten by a late older event. Historical alerts are not retroactively recalculated.

## Four health states
Thresholds are configurable in `saas/config/thresholds.yaml`. Defaults for CPU: Excellent below 60%, Good 60–<80%, Fair 80–<95%, Poor 95% or higher. Other metric thresholds cover memory, disk, latency, loss, connectivity and availability. Anomaly severity can worsen metric health. Fleet state is the worst of recent source signals; stale telemetry and heartbeat downgrade health. At 30 s without a heartbeat, the collector becomes at least Fair; at 60 s it becomes Poor. Watchdog runs approximately every second (actual detection latency must be measured). Transitions record UTC timestamp and reason.

## Explainable AIOps
For each tenant, collector, source and metric, use up to 60 preceding event-time samples. Once at least 8 samples exist, compute rolling median and median absolute deviation (MAD). Score = (value−median)/max(1.4826×MAD, configured floor). A robust deviation of magnitude 4 or above triggers an anomaly, magnitude 8 or above is critical. Critical thresholds cover cold-start periods. Approved local security categories and counts also produce alerts. This is adaptive statistical detection rather than a trained neural model; tuning and false-positive evaluation remain necessary.

Correlate anomalies on the same pseudonymous source and collector within a 120-second event-time window. Incidents retain contributing signals, count, severity, timestamps and a likely cause/remediation recommendation. A network latency/loss pair suggests link degradation, not a proven causal conclusion. Confidence is labeled heuristic, not a calibrated probability. Auth failure bursts suggest inspection of the local authentication records; SaaS never receives those records. Approval requires operator authorization and records a simulation and rollback description. No actual infrastructure commands execute.

## Judge evidence and performance
The proof API reports unique received IDs, retry attempts and measured ingest, render, alert and heartbeat-expiry timing. UI render acknowledgement is an extra integration endpoint proposed for C; sent-ID reconciliation requires the collector/outbox evidence. Missing samples are null. Target: collection-to-dashboard p95 ≤10 s, alert ≤15 s, offline detection ≤60 s, backlog zero lost and duplicate stored records. These are targets, not achieved benchmark claims. Compare exact egress payload and central metadata, inject anomalies, send the same signed payload to both replicas, stop one replica and verify persistence and continuity; compare collector sent IDs after recovery. Measure actual timings on the organizer stream.

## Phase 1 deliverables and limitations
The SaaS scaffold, migration, Dockerfile, threshold config, endpoint proposal and tests are contained in Member B's files. A owns the final contract; C owns the root compose and load balancer. Current static credential provisioning is a demo, not a complete dynamic enrollment service. Production needs managed secrets, TLS end-to-end, scalable storage/pooling, database failover, retention and stronger correlation topology. Test status: seven independent tests passed in the local build environment; ten Postgres-dependent integration tests were skipped because Postgres and its driver were unavailable. Final contract approval, live organizer-stream integration, real failover and performance remain pending.
