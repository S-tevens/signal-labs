# Phase 4 platform: implementation and rehearsal notes

Branch `platform/phase4-member2` starts from main at `1e0053a` and carries the earlier `codex/phase3-platform-dashboard` work. This document reports local checks, not a completed organizer-stream rehearsal.

## Implemented

- **P25:** The live incident workspace shows retained signals, values and units when recorded, detection method, baseline or threshold when available, event and alert UTC timestamps, persistence, and links to received payloads. The recommendation remains a heuristic investigation, not a proven cause. Historical incidents may not contain the new fields; the UI says when they were not recorded.
- **P26:** The default offline threshold is now 40 s (stale remains 30 s). The Phase 3 realtime profile uses a 5 s heartbeat. This changes the shared timing contract and must be reviewed with Member 1 for their chosen heartbeat/profile before merge; shorter timeouts can produce false offline states under delay.
- **P27:** The Received payload page accepts a payload ID and uses the existing tenant-scoped observation API. It presents normalized stored fields, not the original wire bytes. Incident lineage links directly to it.
- **P28/P29:** An automated test verifies eight synthetic normal observations create no incident, followed by one critical CPU observation producing an explainable incident, and verifies cross-tenant payload lookup returns 404. This small synthetic test is not a measured false-alarm rate and does not replace the organizer scenarios or a joint rehearsal.
- **P30:** The presentation outline and viva answers are in [the Phase 4 plan](../phase-4.md). Both members still need to rehearse it together.

## Local verification

- `npm run build`: passed.
- `pytest -q saas collector` against disposable PostgreSQL databases: **167 passed, 3 skipped**. Tests include the Phase 4 synthetic incident, tenant isolation, and an accelerated threshold check.
- A temporary local SaaS with test-only credentials was exercised in a browser. The incident drawer displayed CPU 99%, configured threshold ≥95, method, timestamps and a payload link; the received-payload page displayed the matching stored observation.
- One additional synthetic local run sent a heartbeat and polled the platform after it stopped: an expired-heartbeat Poor reason was observed **40.45 s after the heartbeat response**. This is one run on one machine with a 0.5 s polling interval, not an E29 organizer-stream measurement and not a p95. Repeat from the last heartbeat with the shared harness and profile before claiming the 60 s target.

## Still open for judging

- Member 1 and Member 2 must agree the heartbeat/offline settings, run E29 on the actual organizer stream and retain its raw evidence. Dashboard latency, alert latency and loss/duplicate reconciliation are not newly measured by this platform work.
- Rehearse each actual organizer injection, calculate false/missed alarms with a stated observation window and denominator, and verify grouping without treating grouping ratio as a false-positive rate.
- Check collector-local hold/release, matching IDs and fields, canary scan and the received-payload screen together. The SaaS normalizes payloads; this screen cannot prove byte-for-byte equality.
- The dashboard stream still emits periodic snapshots and render acknowledgements are client-reported; do not claim real end-to-end freshness or a p95 without the measurement harness.
- Repeat the full browser and failure/recovery walkthrough on the final deployment and verify the action workflow is explicitly described as simulated.
