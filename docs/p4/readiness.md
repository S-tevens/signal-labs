# Demo readiness: local work and limitations

This branch adds a live readiness page, fixes the dashboard stream's current-session token, and lets the dashboard and rehearsal observer request lightweight tenant-scoped change notifications. The previous full `snapshot` stream remains the default for older clients. Dashboard change notifications are coalesced for one second, with a nine-second fallback refresh; the backend sends a recovery event after 15 seconds. The stream never sends another tenant's payload data in change mode.

The readiness checklist is a manual, per-browser-session aid. A tick does not prove an item. The platform performance values are client-reported and do not replace independent collector-to-platform ID reconciliation or timestamps from the judging setup.

## Local synthetic rehearsal

[Measurement summary](evidence/measure-20261121T011145Z.md) and [raw timestamp evidence](evidence/measure-20261121T011145Z.json) record a single run with a separate local PostgreSQL database, a single local SaaS instance, the realtime collector profile, the development dashboard open, and synthetic inputs. The run observed:

- Collection to dashboard-path p95 from window start: 3.374 s, 45 samples.
- Hard-threshold alert on dashboard path: 2.91 s.
- Offline detection from last heartbeat: 40.236 s.
- Five-second simulated link outage: 27 created IDs, 0 missing, 0 duplicate rows; replay 5.01 s.

This was one local run, not the organizer stream, not a production capacity claim, and not proof of future results. The dashboard-path figure is the rehearsal harness's fetch-completion proxy, not a measurement of physical display refresh. The live browser was open concurrently. At the time this run started the harness fetched seven data endpoints; it has subsequently been updated to include the dashboard's `/v1/session` fetch too, so these numbers are not a measurement of that exact final harness. The listener shutdown scheduling was also adjusted after the server started; rerun against the final committed build before quoting. The final measurement must use the actual organizer stream and agreed timing definitions.

## Before judging

1. Connect the shared organizer stream and confirm its timestamp, source mapping and units.
2. Use the real collector-local egress panel, hold a payload, show the raw record and canonical queued payload, and follow its ID to the tenant-scoped SaaS and incident.
3. Run the current timing and scenario tools against the final build with the dashboard open. Record all sample counts, false/missed alerts, fail/pass results and independent ID reconciliation; do not substitute the local run above for this step.
4. Demonstrate outage recovery and, if claiming global delivery, a real second region and tenant isolation in the demo environment.
5. Explain the incident's signal, observed value, threshold/baseline, method, times, payloads and recommendation. The evidence graph is not a proven dependency graph, and simulated actions do not execute a fix.
