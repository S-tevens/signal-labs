# Scripts

Everything runs locally on Windows PowerShell with dev credentials. No Docker.

| Script | What it does |
|---|---|
| `run-local.ps1` | Starts Postgres (port 5433), runs the migration, then two SaaS replicas, the collector, the simulator and the dashboard. Flags: `-NoSimulator`, `-NoDashboard`, `-Restart`, `-Status` |
| `stop-local.ps1` | Stops everything it started (`-KeepDb` leaves Postgres running) |
| `demo.ps1 <scenario>` | Injects one live scenario, prints the expected result and what the SaaS did. `-List` shows them all |

## First run

```
pip install -r collector\requirements.txt -r saas\requirements.txt
.\scripts\run-local.ps1
```

If your default `python` lacks the dependencies, point `$env:PYTHON` at one that has them. PostgreSQL is found under `C:\Program Files\PostgreSQL`, or set `$env:PG_BIN`. Logs are in `data\logs`.

## Scenarios

`secret`, `failed-logins`, `cpu-spike`, `latency`, `packet-loss`, `disk`, `alert-storm`, `outage`, `delivery`, `remediation`.

- Run `python simulator\generator.py --seconds 120` (or leave `run-local.ps1`'s simulator running) first, so the SaaS has a baseline.
- `outage` cuts the collector's link, buffers, reconnects and then proves zero loss by comparing payload ID sets.
- `delivery` posts a duplicate, an out-of-order event and a same-ID-different-body payload straight to the SaaS.
- Scenarios on the same host within about 2 minutes join one incident, because correlation is per source and time window.

## Known limits

- Nothing here is production setup: static dev credentials, plain HTTP, one local database.
- `run-local.ps1` has no load balancer, so the collector talks to replica 1 only (the failover proxy is task E12).
