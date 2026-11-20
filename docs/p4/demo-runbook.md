# Demo runbook: start, recover, bundle the evidence

For whoever drives the demo, including Member 2. PowerShell, from the repository root. Dev credentials only; none appear in this page or in the evidence bundle. The scenario-by-scenario walkthrough is in [../p3/collector.md](../p3/collector.md).

## Before the demo

```
$env:PYTHON = "<path to the venv python.exe>"        # only if python on PATH is not the project's
.\scripts\run-local.ps1 -Tls                          # everything, including the simulator and the dashboard
.\scripts\recover.ps1                                 # confirm: every line OK
.\scripts\open-demo.ps1                               # egress panel left, dashboard right
```

- Use `-NoSimulator` if the organizers' stream is the data source or you need a clean count (the scenario check and measurements want this). Use `-Profile default` only to show the slower timing.
- The platform needs about 8 windows of history per metric before it scores deviations from baseline; give the simulator at least a minute.
- Stop everything with `.\scripts\stop-local.ps1`.

## When something goes wrong

Run `.\scripts\recover.ps1` first. It checks the collector, the SaaS entry point, both replicas, the dashboard and Postgres, and puts right the two things a demo most often leaves behind: a SaaS link left down by a scenario, and sending left on hold in the panel. `.\scripts\recover.ps1 -Restart` restarts the whole stack and keeps the data.

| Symptom | Likely cause | Do this |
|---|---|---|
| `run-local.ps1` says nothing started, or errors about a null process ID | A stale `data\run.pids.json` from an interrupted start | `.\scripts\recover.ps1 -Restart` (it removes the file) |
| Panel shows payloads stuck `pending`, strip says HELD | Sending left on hold | Click **Release**, or `.\scripts\recover.ps1` |
| Pending count grows, strip says link down | A scenario cut the link and did not restore it | `.\scripts\recover.ps1`; the buffered payloads then go and the IDs reconcile |
| Dashboard shows old data or "stale" | Collector stopped, or the platform entry point is down | `.\scripts\recover.ps1`; check the collector line first |
| One SaaS replica DOWN | Expected after the `failover` scenario | Nothing is lost; `-Restart` brings it back |
| Dashboard DOWN but everything else OK | Started with `-NoDashboard`, or Node not installed | `.\scripts\run-local.ps1` without `-NoDashboard`. The egress panel and the API still work |
| Two scenarios merge into one incident | Correlation is per source within 120 s | Wait 2 minutes between scenarios on one host, or use a fresh host |
| Postgres DOWN | Port 5433 busy or the cluster did not start | `.\scripts\recover.ps1 -Restart`; the log is `data\logs\pg.log` |
| A step fails on stage | Any of the above | Say so, run `recover.ps1`, repeat the step. Do not switch to mock data: the point is that the live path works. The `trace` and `verify` commands show the evidence either way |

Logs are in `data\logs` (collector, both replicas, proxy, Postgres). They hold no secrets by design (raw records stay in the collector's database, not in its logs).

## Evidence bundle

```
.\scripts\bundle-evidence.ps1
```

Writes `data\evidence-bundle-<time>.zip` with every measurement, proof run, trace, scenario check and rehearsal, the demo guides, the thresholds, policy and mapping files, and a `MANIFEST.txt` with the commit, branch, whether there are uncommitted changes and the collector timing in use. It refuses to build if any file looks like it contains a credential (the one known fake test key printed by the `secret` scenario is allowed). Run it after the final rehearsal so the bundle matches the commit the judges will see, and note the commit in the rehearsal record in [../phase-4.md](../phase-4.md).

## Final rehearsal order (about 20 minutes)

1. `run-local.ps1 -Tls -NoSimulator`, then `recover.ps1`.
2. `rehearse.ps1` (scenarios, then proof checks), or the steps one by one from the guide.
3. `scenario-check.ps1` (expected vs actual, false and missed alerts).
4. `measure.ps1` (dashboard, alert, offline, delivery), or `-WithMeasure` on the rehearsal.
5. `trace.ps1 --demo` (one payload from raw record to recommendation).
6. `bundle-evidence.ps1`.

Repeat steps 2 to 4 on the organizers' stream once it is connected; the numbers above come from the simulator.
