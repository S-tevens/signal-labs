# Platform completion: Phase 3 and Phase 4

This branch starts from `main` at `1a6de4c`. Results below are local synthetic checks on one machine, not organizer-stream or production results.

## Requested tasks

| Task | Implementation / verification | Remaining boundary |
|---|---|---|
| P18 | PostgreSQL sends a tenant identifier on committed payload, collector and incident changes. Each SaaS replica listens and wakes that tenant's SSE streams. Initial snapshot and a 15 s recovery snapshot cover reconnects; the dashboard has a 9 s fallback. The client acknowledges after React commit and a paint opportunity. Performance proof shows sample count, window and last update. | Apply migration `003.sql` before starting replicas. Render acknowledgement is client-reported, not a physical display measurement. Repeat end-to-end p95 using Member 1's harness on the shared stream. |
| P21 | Dashboard displays the tenant and region returned by the authenticated `/v1/session`; live region selector is disabled. The client derives collector region from the authenticated session when metrics are missing. | Select another tenant by configuring its dashboard token and region endpoint; a region dropdown cannot change authorization. Browser tokens in Vite configuration are for local demos, not production authentication. |
| P22 | An India instance and a separate Europe instance ran against separate databases. The Europe service accepted and returned its own synthetic payload; its token was rejected by the India instance. Browser showed `t-eu` and Europe. Local ingest probe: **200/200 accepted, 0 failed, 0.855 s, 233.86 payloads/s, client p95 0.018 s**, one collector, one tenant, four workers, localhost. | This is a small synthetic single-run figure, not a production capacity claim, a multi-tenant scaling test, or end-to-end latency. The per-tenant advisory transaction lock serializes writes and is a plausible bottleneck, but was not isolated or measured in this probe. |
| P23 | In a browser against the test SaaS: opened an incident's explanation, followed its payload to the stored observation, opened the incident object and health history, and proposed, approved and rolled back a **simulated** action with its audit trail. | Repeat against the final integrated build, tokens and data; these local actions did not execute infrastructure commands. |
| P25 | Incident explanation shows retained value, method, threshold or baseline where recorded, event and alert UTC times, payload link, and recommendation. Local 99% CPU test showed threshold ≥95, threshold fallback and the correct payload. | Historical incidents may lack fields. The recommendation is a heuristic investigation, not a proven cause. |
| P27 | Collector local egress panel has a configurable dashboard URL and opens the selected payload ID directly in the tenant-scoped Received payload page. Browser tested the real collector → SaaS flow with a synthetic CPU event. | Select the correct dashboard URL/token. Only the payload ID is passed in the URL; normalized SaaS fields are not byte-for-byte wire proof. Coordinate this small `collector/ui/` change with Member 1. |
| P28 | Definitions below match Member 1's scenario-check implementation and recorded evidence. | This document proposes the shared definitions; Member 1 must confirm them. The recorded simulator run does not establish real-world false-positive rates. |
| P29 | Two tenant/region browser sessions, incident explanation, stored payload, object explorer, history and simulated actions were checked with disposable test data. | Organizer-stream timing, full failover/recovery, actual user authentication and final deployment remain to be rehearsed together. No sample results should be presented as live measurements. |
| P30 | The short story and Q&A are below and in [Phase 4](../phase-4.md); Member 1's [demo runbook](demo-runbook.md) covers startup and recovery. | Both members must rehearse and use actual results from the final build. |

## Push and isolation check

With two local SaaS replicas sharing the India database, a payload was POSTed to replica 1 while an authenticated SSE stream was connected to replica 2. The stream included that payload after **0.037 s** in a single run. A second tenant's stream received no update during a one-second observation. Database integration tests check that notifications contain only the tenant identifier and that a rolled-back transaction emits none. These checks do not establish p95 or production-scale isolation.

The database notification includes a tenant ID and no payload fields. Tenant authorization and row-level security still apply to the snapshot. Direct database access is trusted infrastructure access; notifications are not a replacement for database access control. A listener reconnects after a database connection failure; the periodic fallback can temporarily delay an update.

## Proposed scenario definitions for Member 1 to confirm

These match `simulator/scenario_check.py` and [the recorded scenario run](../p3/evidence/scenarios-20261120T184848Z.md):

- **False alarm:** an alert on a normal decoy source at any time, or on a scenario source before its injection. Report normal host/metric/windows, duration and total separately.
- **Missed:** an expected signal absent on the scenario source after injection. **Extra:** a signal observed after injection that was not expected.
- **Grouped:** related alerts from one source appear in the same incident. The grouping count is not a false-alarm rate. Incident signal retention is capped, so label the retained scope.
- The recorded run used 60 s normal, 20 s injection and 20 s normal, with about 1,860 normal metric-windows; it reported zero false alerts, missed expected signals or extra signals in that run. It was a short simulator run, not the organizer stream. Recovery to normal was not evaluated.

## Short demo story and Q&A

1. “Organizations need to spot issues while keeping raw telemetry and secrets in their own environment.”
2. Member 1 shows a real local record and allowed payload, then opens that same ID on the dashboard.
3. Member 2 opens the actual incident and explains the source, signal, value, method and threshold/baseline, UTC times, contributing payload and why the recommended investigation follows.
4. Together, show measured timing, the outage/recovery ID reconciliation and actual scenario results. Report any missed target or failed scenario.
5. Explain that correlation groups related alerts and that the recommendation is a heuristic. Actions are simulated and do not execute commands.

**Why not send raw logs?** They can contain secrets or personal information; the collector retains raw data locally and only approved metadata is sent. **How do you know why it alerted?** Show the real signal and detection method/threshold or baseline and follow its payload ID. **Does correlation prove cause?** No; it provides related evidence for investigation. **Are false alarms eliminated?** No. The stated synthetic run has a limited window and denominator. **Can it remediate automatically?** No; the current actions are simulations with review and audit. **Are the latency numbers guaranteed?** No; use the latest measured evidence and disclose the setup and any failure.
