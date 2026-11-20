# Measurement evidence

Each `measure-<UTC time>.md` / `.json` pair is one run of `.\scripts\measure.ps1` (task E14). The `.md` is the summary table with the settings used; the `.json` holds every raw timestamp the verdicts were computed from.

How to read a run:

- **Live traffic only.** Every test sends records timestamped "now" from a unique host, so the numbers are not skewed by old data or by other traffic.
- **Two paths.** "API" is the earliest the data could be shown (the harness polls twice a second). "Dashboard path" does what the real dashboard does when the platform pushes a snapshot: fetches the fleet, incidents, proof and four metric series, then renders.
- **Two definitions of latency.** The collector sends one summary per window. "From newest record" starts the clock at the payload's own event timestamp. "From window start" starts it at the earliest record the window could hold, which is the strict reading. The verdict uses the strict one.
- **Offline** is measured from the last heartbeat (the strict reading) and from the moment the collector was killed.
- **One machine, one clock.** If the organizers measure across machines, agree a time source first.
- The settings the run used (collector timing profile and the platform's thresholds) are at the bottom of every `.md`.

Compare runs by the **settings** section: a result only means something alongside the window, grace, send interval and thresholds it was measured with.
