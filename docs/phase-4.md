# Phase 4: Final demo, validation and presentation — evidence and work split

Plan based on `main` at `61ad51b` and the Phase 4 evaluation sheet. The sheet asks for a live end-to-end demonstration, correct responses to injected scenarios with few false alarms, **explainable AIOps (weighted higher)**, honest limitations and a clear presentation. A checkbox is earned by what works during judging, not by completing this document.

**Status language:** verified = supported by a specific test or recorded run; built = code exists but this demo has not been checked end to end; open = work or evidence still needed. Prior local measurements are not evidence that the shared organizer stream has passed. Refresh the status and attach the actual evidence after rehearsal.

Two members, same split as [Phase 3](phase-3.md): Member 1 owns the collector, simulator, scripts and local proof; Member 2 owns the SaaS, dashboard, AIOps explanations and story. Both rehearse and answer questions. Work on `edge/<topic>` and `platform/<topic>` branches, coordinate changes at the seams, and keep the payload contract stable unless both agree.

## 1. What the judges must see

| Phase 4 criterion | Show it live | Evidence / honest boundary |
|---|---|---|
| **End-to-end: raw source → actionable recommendation** | Start at a real record on the collector; follow the sanitized payload ID through SaaS ingest to an incident, its signals and a specific investigation recommendation | Raw data stays in the local panel. Trace one actual payload, not a conceptual diagram or a fixed dashboard example. Confirm the same ID at both ends; compare fields where supported |
| **Correct response to injected scenarios; few false alarms** | Agree the expected result before each injection; show a normal period, then the organizer's injected spike/event and recovery; count missed, extra and grouped alerts | Record the observation window and denominator. A grouped-alert ratio is not by itself a false-alarm rate; do not claim zero false alarms from one short run |
| **Explainable AIOps — weighted higher** | Open the actual incident and explain **why it was flagged, which signals contributed, and why this action was suggested**; follow the evidence to payload IDs and timestamps | Identify whether the detector used a threshold, baseline deviation or local event summary. A correlation and confidence label are heuristics, not proof of root cause |
| **Honest limitations; innovation in privacy / correlation / noise** | Show the local redaction and allow-list, then explain the grouping and what it reduces; name what is not implemented or not measured | No claim of perfect privacy, proven cause, production readiness, autonomous remediation or guaranteed global scale. Actions are simulated |
| **Clear presentation; confident answers** | Both members tell one consistent story, exchange roles smoothly, explain a failure and answer follow-up questions from the running system | Prepare a short script and rehearse without switching to mock data when a live step fails |

The Phase 3 mandatory items still apply: **shared organizer telemetry stream**, **real-time results measured from timestamps**, and **the real collector-local egress proof panel**. The central dashboard's synthetic egress example and the conceptual Data Flow map do not replace the real panel or a live trace.

## 2. Current evidence and gaps

The following describes the checked-in evidence on `main`, not a fresh Phase 4 verification:

| Item | Status / prior evidence | Before judging |
|---|---|---|
| Organizer stream | Open; its format was unknown in the Phase 3 plan | Integrate the actual stream, identify timestamps and units, and demonstrate on that same stream. Do not substitute the simulator for the judge's stream |
| Privacy and egress | Local proof panel and policy are built; Phase 3 identified a need to hold a payload and match it with SaaS data | Demonstrate a raw record with a test secret locally, the exact outgoing allowed payload and its matching received record. Run canary checks if available; report their scope |
| Dashboard timing | One local `realtime` run measured strict collection-to-dashboard p95 **5.951 s (90 samples)**; default runs failed the 10 s target | Repeat with the real stream and agreed measurement method. Show p95, sample count, measurement window, settings and raw timestamps; see [measurement summary](p3/evidence/SUMMARY.md) |
| Alert timing | Local realtime run: hard-threshold alert **3.576 s**; a separate baseline-deviation run measured **6.58 s** | Repeat with the actual injected scenarios; identify event time and alert-visible time. Results from different runs are not a single combined measurement |
| Offline timing | Prior local runs **failed**: 60.16 s and 60.28 s from the last heartbeat with a 60 s setting | Coordinate the heartbeat and stale/offline thresholds, reduce the threshold with sufficient margin, then rerun and show the result. Do not describe this as passed until measured |
| Outage delivery | One local realtime run: **136 created, 0 missing, 0 duplicate rows**, replay about 5.77 s | Repeat with the integrated stream; compare independently enumerated created/sent and received IDs. Duplicate attempts are not the same as stored duplicates |
| Explainability and noise | Incident lineage, thresholds, persistence and correlation exist; Phase 2 notes that false-alarm rate and some browser screens were not checked | Verify the actual incident workspace, all linked evidence and recommendation in the browser; run and document a normal baseline and injected scenarios |
| Safe actions | Proposal / approval / audit workflow is a **simulation** | Demonstrate as a proposed investigation or simulated action only. No infrastructure command is executed |

The cited runs used one machine, one clock and small samples. Prior values are local test results, not production guarantees or proof that the organizer's judging run will pass.

## 3. Live demo: one story from source to recommendation

Prepare the shared stream and the actual judge-provided scenario. Use test secrets only, never real credentials. Member 1 drives the local environment; Member 2 drives the platform.

1. **Before:** explain the problem in one sentence: teams need to identify infrastructure problems without copying sensitive raw logs to a central service. Show the collector is connected and the correct tenant is selected.
2. **Local source:** show one raw organizer record and its event time in the collector-local panel. If the organizer's record does not contain a safe test secret, use the agreed canary procedure separately and label it.
3. **Privacy boundary:** show the local filter / policy and the exact payload before transmission, with its ID. Point out what remains local and what is sent. If hold-and-release is not ready, state that limitation; do not claim a pre-send capture you cannot show.
4. **Platform reception:** release or send the payload and find the same ID in the authenticated tenant's SaaS observation. Compare the allowed fields against the local panel. Distinguish original outgoing bytes from a normalized stored representation; field equality is not proof of byte-for-byte equality.
5. **Inject:** ask the organizer to trigger the scenario or use the agreed live injection. State the expected signal and expected incident before it happens. Show event time, detection and the resulting health or incident.
6. **Explain:** open the incident and name the signals, observed values, baseline or configured threshold, persistence where applicable, source and contributing payload IDs. Show how the system grouped related alerts.
7. **Recommend:** read the recommended investigation and explain how the evidence supports it and what remains uncertain. If showing the action workflow, clearly say it is simulated and subject to review.
8. **Prove reliability:** if time permits, interrupt SaaS delivery, show the local buffer, restore service and reconcile IDs. Show a fresh timestamp-based measurement for dashboard, alert and offline detection and the measured pass/fail result.
9. **Close:** summarize the privacy boundary and the operational result. State one or two real limitations and answer questions using the running system.

Keep a note of the tenant, collector ID, source ID, payload ID, incident ID, timestamps and scenario for each run. Never put real secrets or credentials in evidence files.

## 4. Scenario and validation matrix

The following are expected checks, **not claims that the organizer will inject every scenario**. Confirm its actual scenarios and inputs first. Existing local simulator commands help rehearse, but they do not replace the shared stream. Run isolated sources or allow for the configured correlation window so unrelated scenarios are not accidentally merged.

| Scenario | Expected behavior to verify | Evidence / possible failure |
|---|---|---|
| Normal baseline | Measurements arrive; no unsupported critical incident during the observed normal period | Count false incidents / alerts and state duration, sources, conditions and denominator; a quiet short run is not a general false-positive rate |
| CPU spike / baseline deviation | The affected source's value and detection method appear in an incident with a relevant investigation | Record injected value, baseline or threshold, persistence, event/alert timestamps and actual vs expected result |
| Latency or packet loss | The correct network signal appears, associated with the correct source | Check units, timestamps and affected source. Don't infer a network cause from one metric alone |
| Failed logins | Local activity becomes an allowed count/category; the platform correlates an event without raw login records | Compare a test record and the outgoing payload locally; check no username or test secret appears in the allowed metadata |
| Alert storm | Related alerts group into an incident without losing the individual evidence references | Show total correlated alerts and incidents over a named scope; distinguish noise reduction from false-alarm rate |
| Collector offline | Heartbeat age crosses the configured timeout; the collector is marked Poor within the required time | Measure from the last heartbeat and report actual cutoff and time; an offline collector does not prove its monitored service is down |
| SaaS outage / restore | The collector buffers eligible payloads and retries; after restoration, IDs reconcile | Capture created/sent/received ID sets and duplicates; do not rely on a constant `stored_duplicates` field |
| Duplicate or late event | Repeat delivery is handled idempotently; late data does not incorrectly overwrite newer live state | Show payload IDs and outcomes. Document exactly which event ordering was exercised |

Useful local rehearsal commands, after the stack is configured and running:

```powershell
python simulator/scenarios.py --list
python simulator/scenarios.py cpu-spike
python simulator/scenarios.py failed-logins
python simulator/scenarios.py alert-storm
.\scripts\measure.ps1
```

Commands may change state and inject data; run them only in the intended demo/test environment. See [measurement evidence](p3/evidence/README.md) for the timing definitions and [Phase 3](phase-3.md) for integration tasks. Record exact commands and results actually used in rehearsal.

## 5. Work split and acceptance criteria

**P0** = needed to demonstrate a sheet criterion or mandatory item; **P1** = strengthens the demo. Assign names and dates before starting.

| | Member 1: Edge | Member 2: Platform |
|---|---|---|
| **Name** | _______ | _______ |

### Member 1: Edge

| ID | Priority | Task | Done when |
|---|---|---|---|
| E26 | P0 | Integrate organizer stream and record its mapping, event timestamp, units and time source | Real organizer records reach the collector and produce contract-valid metadata; a teammate can reproduce it |
| E27 | P0 | Prepare the real local egress, safe canary and payload-ID comparison with Member 2 | A test record and its exact outgoing payload can be shown locally; the received record matches on compared fields and the scope of any canary scan is recorded |
| E28 | P0 | Rehearse baseline, agreed injected scenarios and failure/recovery | Each scenario has expected/actual outcome, timestamps, relevant IDs and a result; false and missed alerts are counted for the stated observation window |
| E29 | P0 | Rerun timing and ID reconciliation with the agreed realtime profile | Evidence includes all three measured targets and independent ID sets with sample sizes, settings and pass/fail; failures remain visible |
| E30 | P1 | Prepare demo startup, recovery steps and evidence bundle | Member 2 can start and recover the stack using written instructions, without exposing credentials |

### Member 2: Platform

| ID | Priority | Task | Done when |
|---|---|---|---|
| P25 | P0 | Complete the incident explanation and browser walkthrough | The actual incident shows the observed signals, values, detection method/threshold or baseline, event time, payload IDs and the reason for the proposed investigation, or clearly identifies missing fields |
| P26 | P0 | Coordinate and fix stale/offline settings and measure with E29 | Poor is observed within 60 s from the last heartbeat, with margin measured on the real setup; settings and evidence are recorded |
| P27 | P0 | Provide a tenant-scoped received-payload view or reliable API walkthrough | The ID selected in the collector's local panel opens the same stored observation; normalized data is not described as exact wire bytes |
| P28 | P0 | Validate injected scenarios and noise with Member 1 | Correct and missed detections, false alarms and grouped-alert counts are recorded with clear definitions and observation windows; unsupported claims are removed |
| P29 | P0 | Verify live data, incident lineage, timing and presentation in the browser | No sample figures are presented as live; stale/unavailable states are visible; screen and API results agree for the demonstrated incident |
| P30 | P1 | Prepare the short story, Q&A and limitation slide with both members | Both can explain privacy, correlation, detection, timing and the simulated action without claiming unmeasured outcomes |

**Shared:** agree thresholds, window length and timing definitions with the collector owner before changes; preserve API and payload-contract compatibility. Freeze features early enough for one complete rehearsal on the exact build and configuration.

## 6. Explainable AIOps: what to say

Use the **actual values from the live incident**. This is a template, not a prewritten result:

> “We flagged **[signal]** for **[source]** at **[time]** because **[value]** was **[above/below threshold, or different from baseline]**. The detector used **[method]** and **[persistence, if applicable]**. We grouped **[number]** related alerts from **[signals]** into this incident. The evidence comes from payloads **[IDs]**. We suggest **[investigation]** because **[link to the signals]**. This is a recommendation, not proof that **[possible cause]** is the root cause.”

For an event summary, explain the local category, count and time window instead of inventing a numerical baseline. For an offline collector, use last heartbeat and timeout; distinguish monitoring availability from service availability. If a field or recommendation is missing, say so and use the real supporting evidence available.

## 7. Presentation and viva practice

**Suggested 5-minute structure** (adjust to the judges' allotted time):

| Time | Speaker | What to cover |
|---|---|---|
| 0:00–0:30 | Either | Problem, users and why centralized raw telemetry can expose sensitive data |
| 0:30–1:30 | Member 1 | Live source, local processing, policy and actual outgoing payload |
| 1:30–3:00 | Member 2 | Received metadata, injected scenario, incident evidence and explainable recommendation |
| 3:00–4:15 | Both | Outage/retry or timing proof, measured results and any failure |
| 4:15–5:00 | Both | Privacy/correlation benefit, limitations and questions |

**Practice questions:**

1. **What problem are you solving?** Teams need operational visibility across environments while reducing exposure of sensitive raw telemetry.
2. **What stays local?** Original records and secrets should remain in the customer environment; only allow-listed metadata is sent. Show the local proof rather than claiming that every possible secret is detected.
3. **Why was this alert raised?** Give the actual signal, value, source, time and rule or baseline, then show the payload evidence.
4. **Is it AI and does it prove the cause?** The current AIOps uses rules and statistical heuristics for detection and correlation. Its recommendation is an investigation hypothesis, not a proven root cause.
5. **How do you reduce noise?** Persistence can suppress brief deviations and correlation groups related alerts. Show counts and the scope; do not confuse grouping with a measured false-positive rate.
6. **What happens during an outage?** The local outbox buffers and retries; unique payload IDs support deduplication. Prove the demonstrated run by comparing ID sets after recovery.
7. **Can the system fix an issue automatically?** Current actions are simulations with review and audit; they do not execute infrastructure commands.
8. **How do you know the timing targets pass?** Show the latest timestamped measurements, sample counts, settings and pass/fail against the targets. Disclose any failure, including offline detection until it is fixed and retested.
9. **What is the biggest limitation?** State the actual current gap, such as incomplete organizer-stream verification, limited test samples, missing byte-for-byte proof or unverified scaling.

## 8. Rehearsal record and final checklist

Write the rehearsal date, commit, machine, profile, stream source, tenant, participants and links to sanitized evidence here or in a dedicated evidence file:

| Run / evidence | Scenario or measurement | Expected | Actual | Pass / fail | Follow-up |
|---|---|---|---|---|---|
| _______ | _______ | _______ | _______ | _______ | _______ |

- [ ] Shared organizer stream connected; its mapping, time and units verified. **Open:** the format is not known yet (E26).
- [x] One raw local record traced through the real outgoing payload and the same tenant-scoped received payload to an incident and recommendation. Done on simulator data with `scripts/trace.ps1 --demo`; repeat on the organizer stream.
- [ ] Correct expected vs actual responses documented for the organizer's live scenarios, including a normal observation period and false/missed alerts. **Open:** scenario check ran on the simulator only (7 of 7 passed, 0 false alarms in about 1,860 normal metric-windows); not the organizer's scenarios.
- [x] Explain why flagged, which signals contributed and why the recommendation follows; show IDs and timestamps. Evidence: the trace's incident hop and Member 2's incident explanation (P25).
- [x] Privacy, correlation and noise benefits demonstrated within the scope actually tested; limitations stated honestly.
- [x] Timestamped dashboard ≤ 10 s, alert ≤ 15 s and offline ≤ 60 s results shown with sample counts and configuration; failures reported, not hidden. Latest: [rehearsal record](p3/evidence/rehearsal-20261120T192509Z.md) and [summary](p3/evidence/SUMMARY.md).
- [x] Forced outage, buffering and recovery checked; created/sent/received ID sets and duplicates independently reconciled.
- [x] Real local egress proof panel shown; no real secret or credential is included in evidence. The evidence bundle script refuses to build if a credential-like value is present.
- [ ] Both members complete a timed rehearsal and can answer the viva questions. **Open:** the automated rehearsal is recorded; a timed run by both people and the Q&A practice are still to do.
- [ ] Final evidence references the exact commit and configuration that judges will see. **Open:** freeze the build, then run `scripts/bundle-evidence.ps1` and note the commit here.
