# SaaS and AIOps: Phase 1 explanation

Signal Labs keeps raw records in the customer environment and sends allow-listed metadata to an authenticated regional SaaS. The backend maps collector credentials to tenant and collector identity, verifies HMAC signatures, and rejects payloads outside the frozen contract. Dashboard bearer credentials are tenant-scoped; PostgreSQL row-level security limits data access. The local raw and egress interfaces remain the edge owner's responsibility.

The service records collector states and UTC history, flags statistical deviations from a rolling median/MAD, correlates signals from the same pseudonymous source, and returns a recommendation with its supporting reasons. Baseline anomalies require persistence; critical thresholds and security summaries can alert immediately. Confidence is heuristic.

The current implementation supports stateless app replicas sharing a regional Postgres database and separate databases bound to different regions. A shared database remains a single point of failure; failover proxy, TLS, real geographic deployment and organizer-stream validation are integration work. Local aggregation and policy code are present on the merged edge branch and need joint validation. One-time enrollment and action approvals are prototype features: actions are simulated, audit records identify role rather than individual user, and production needs managed secrets and stronger identity controls.

See [platform design](../p2/saas.md) and [architecture diagram](../p2/architecture.md) for implementation and limitations.
