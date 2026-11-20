# Limits slide and agreed definitions

Member 1 (collector side) confirms the definitions proposed in [platform-completion.md](platform-completion.md), and lists the limits to state honestly when presenting. Every figure below comes from a file in `docs/p3/evidence/`; none is a claim about the organizer's stream.

## Definitions (confirmed, as implemented in `simulator/scenario_check.py`)

- **False alarm:** an alert on a normal decoy source at any time, or on a scenario source before its injection. Report it with the normal host, metric and window counts and the duration, never as a bare number.
- **Missed:** an expected signal that never appeared on the scenario's own source after the injection.
- **Extra:** a signal on the scenario's source after the injection that was not expected.
- **Grouped:** alerts of one source that ended up in the same incident. Grouping is noise reduction, not a false-alarm rate. The platform caps the retained signals per incident, so say "of the retained signals".
- **Alert time:** from the injected event's timestamp to the moment the alert exists on the platform. **Dashboard time:** from the earliest record the window could hold to the moment a dashboard-style client could show it (the strict reading). **Offline time:** from the last heartbeat to the state Poor.
- **Pass for a scenario:** the expected signals appear on its own source, nothing extra after injection, nothing before it, and every expected alert within 15 s (a storm must also be one incident).

## Limits to state

1. **Simulator, one machine, one clock.** All measurements are single runs on one machine with 30 to 140 samples. Margins under about one second are noise: say "6 to 7 s", not "6.01 s".
2. **Not the organizer's stream.** Format, units and timestamps of that stream have not been verified yet. The scenario results (7 of 7, zero false alarms in about 1,860 normal metric-windows) are a small simulated run, not a general false-alarm rate.
3. **Redaction is rule-based.** It can miss a secret in a format it does not know. The privacy claim rests on the allow-list: free text and raw fields cannot travel in a payload at all, whatever the redaction finds. The canary scan proves that its eight planted secrets did not travel, not that no secret ever could.
4. **Recommendations are heuristics.** Detection uses thresholds, rolling statistics and local event summaries. A recommendation is an investigation lead, not a proven root cause, and the confidence label is not a calibrated probability.
5. **Actions are simulated.** Propose, approve, roll back and audit exist; nothing is executed on any system.
6. **Field equality, not wire bytes.** The received payload is compared field by field. The platform widens timestamps, so it is not a byte-for-byte proof.
7. **Heartbeat has no uptime.** The platform contract has no field for it; the heartbeat carries process CPU, memory, disk share and a configuration hash.
8. **Single-machine platform.** Two replicas behind a small failover proxy, one development Postgres, one extra region run locally on its own database. No cross-region latency or large-scale figure has been measured (see the scale note when it is added).
9. **Local inputs are unauthenticated.** The UDP, TCP and file inputs bind to this machine by default and are for trusted networks only. Hold and release only control this collector's own outbox.
10. **Recovery is not judged.** The scenario check does not evaluate health returning to normal after an injection.

## Q&A pointers

Questions and answers are in [../phase-4.md](../phase-4.md) section 7 and [platform-completion.md](platform-completion.md). For any "how do you know" question, run the matching command live instead of describing it: `trace.ps1 --demo` (one payload end to end), `verify.ps1` (egress log equals what the platform stored; no canary anywhere), `scenario-check.ps1` (expected versus actual), `measure.ps1` (timing), `demo.ps1 outage` (buffering and ID reconciliation).
