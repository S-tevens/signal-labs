# Final demo proof: local rehearsal

This branch adds a tenant-scoped **Trace a payload** page and API. Given an ID from the real collector-local egress panel, it shows the stored observation, event and receipt times, linked retained incident signals and the recommendation. Raw records never go through the central SaaS. A normal payload can have no incident; a missing or expired link is reported rather than invented. The trace and its recommendation are evidence for an investigation, not a proven root cause.

The Demo readiness page shows actual retained correlated alerts and incidents and a grouping ratio. This is not a false-alarm rate. Its platform event-to-alert measurement can include intentionally held, buffered or backdated records; the independent measurement harness records the time of the controlled spike separately.

## Guided privacy demonstration

On an isolated local test stack:

```powershell
.\scripts\trace.ps1 --demo --hold
```

This injects **synthetic** failed logins with a test password, holds delivery, waits for the resulting pending payload, checks the SaaS returns 404 for that ID, then pauses so the local operator can inspect the collector panel. Press Enter to release and trace the same ID through the stored observation and recommendation. The collector's five-minute hold timeout still applies. If input ends early, the tool attempts to release the hold. It refuses to take over a hold that was already active. For the real organizer stream, use the real local panel to hold and release the organizer's payload rather than claiming the synthetic demo is their data.

Raw record text is displayed only in the local console and is omitted from saved trace evidence even when `--show-secrets` is requested. Default console masking uses known patterns and may miss unknown formats. The outgoing digest covers one canonical queued payload, not the full batched HTTP request; the SaaS comparison checks normalized fields, not byte-for-byte wire equality.

## Local synthetic evidence from this branch

- [End-to-end held trace](../p3/evidence/trace-bb3b7d4f-20261121T013737Z.md): synthetic 30-event failed-login burst, held locally, not visible at the SaaS until release, then same ID linked to an incident and a review recommendation. Saved evidence omits raw text. The 404 check and pause were observed in the interactive run, while the linked trace documents the post-release stages.
- [Seven injected scenarios](../p3/evidence/scenarios-20261121T013534Z.md) and [data](../p3/evidence/scenarios-20261121T013534Z.json): 45 s normal, 15 s injection, 15 s recovery, seed 13; seven passed, zero false alerts in the defined window, zero missed and zero extra expected signals. Approximately 1,392 normal metric-windows were counted. The check does not judge return to normal, and this is not a general false-positive rate.
- [Timing and delivery](evidence/measure-20261121T013118Z.md) and [raw timestamps](evidence/measure-20261121T013118Z.json): one local realtime run with dashboard open measured 3.631 s dashboard-path p95 (48 samples), 2.154 s for the hard-threshold alert, 40.043 s from last heartbeat to Poor, and 27 created IDs with zero missing or duplicate rows through a five-second link outage. The dashboard-path figure is a fetch-completion proxy, not a physical display measurement. This run used the updated eight-endpoint harness on one machine and one SaaS replica without a proxy.

These runs used a development database, test credentials and synthetic traffic. Some trace/UI code was refined after the timing run, so this is not evidence for the final committed build. Do not present it as organizer-stream or production proof.

## Still needed with the team and organizers

1. Merge the intended final branches, connect the **actual shared organizer stream**, confirm mapping and timestamps, and run the complete raw record → held payload → same received ID → incident → recommendation story.
2. With the actual dashboard open on the final configuration, repeat timing, offline and outage/ID reconciliation. Report failures and sample counts instead of substituting the local numbers above.
3. Run the judges' actual injected scenarios and record expectations, false/missed/extra alerts and grouping scope. A short simulator run is not a general false-positive rate.
4. If claiming the global-ready bonus, demonstrate actual regional routing/residency and tenant isolation. Current remediation remains simulated and does not execute infrastructure changes.
5. Rehearse the presentation and explain each signal, value, method and recommendation; correlation does not prove root cause.
