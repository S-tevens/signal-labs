# Phase 3 platform work

Branch: `platform/phase3`. This branch also includes the existing Analytics and Data Flow dashboard work.

## Started

- Data Flow includes a live status panel for the authenticated tenant: collector count, proxy status, replica health when the local proxy exposes it, and retained payload/incident counts from the region's database. A missing proxy status endpoint is reported as unavailable. The architecture map remains conceptual.
- Health reasons identify the worst recent signal, source, event time and, when available, its value and applicable threshold. Heartbeat reasons include age and configured cutoff. The Health History page displays the actual SaaS thresholds.
- Authenticated session, health-threshold and system-status endpoints support the dashboard. Counts are scoped using the authenticated tenant's database context.

## Still required

- The dashboard stream currently uses periodic snapshots; true push and measured p95 render latency remain to be implemented and verified.
- The payload comparison view, complete incident timing evidence, and end-to-end organizer-stream tests remain open.
- Threshold and collector timing changes require agreement with Member 1 and a measured baseline. The current configuration retains its existing 30-second stale and 60-second offline thresholds; it does not establish that the Phase 3 latency targets are met.
- Run and document failover and regional checks against the integrated deployment. The local proxy status endpoint must be reachable through the dashboard proxy to display the health of every replica.
