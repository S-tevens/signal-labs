# Evaluation evidence: incident and privacy views

This branch improves the required end-to-end and explainable-AIOps demonstration. It does not establish that the organizer-stream or timing criteria have passed.

## What to show

1. In the collector-local egress panel, hold a payload and show the source record, sensitive spans, policy markings and queued payload. Expand **Canonical queued payload bytes**: the displayed UTF-8 text hashes to the displayed SHA-256. The hash is for one canonical payload, not the full HTTP request, which wraps one or more payloads in an array. The panel's leak check searches the retained local spans shown; it is not proof that every secret format is detected.
2. Release the payload and open the matching ID on the tenant-scoped Received payload page. The SaaS displays normalized stored fields, not the original HTTP bytes. Verify the same ID and fields; do not claim a byte-for-byte match between the UI and the request without separate evidence.
3. Open an actual incident. The **Incident evidence graph** follows the collector, pseudonymous source, retained payload IDs, incident and recommendation. These are evidence relationships, not a topology model or proof of root cause.
4. The **Timeline of retained evidence** shows recorded event and alert timestamps in UTC and links to payloads. Signals can be capped by retention; missing timestamps are omitted. An event time is not a full recovery timeline or proof of when an operator saw an alert.
5. In **Why was it flagged?**, show observed signal, threshold or baseline and method, then explain the recommended investigation. Recommendations are heuristic and actions are simulated.

## Required live checks before claiming success

- Integrate and demonstrate the shared organizer stream; its content and availability cannot be inferred from the local simulator.
- Measure dashboard ≤ 10 s, alert ≤ 15 s and offline ≤ 60 s from agreed timestamps on that setup; show sample counts and the actual result.
- Show local buffering and retry through an outage; independently compare sent and received payload IDs for loss and duplicates.
- Rehearse injected scenarios and false-alarm counts with the agreed observation window and denominator.
- Verify tenant isolation, TLS configuration and local egress proof on the exact demonstration build.

Predictive forecasting, adaptive telemetry and a what-if simulator are not implemented by this branch. They are not claimed as evaluation-sheet requirements. Correlation is not a proven root cause, and no unvalidated forecast is presented as fact.
