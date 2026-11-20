# Scripts

Everything runs locally on Windows PowerShell with dev credentials. No Docker.

| Script | What it does |
|---|---|
| `run-local.ps1` | Starts Postgres (port 5433), runs the migration, then two SaaS replicas, the collector, the simulator and the dashboard. Flags: `-Tls`, `-NoSimulator`, `-NoHostTelemetry`, `-NoDashboard`, `-Restart`, `-Status` |
| `stop-local.ps1` | Stops everything it started (`-KeepDb` leaves Postgres running) |
| `gen-certs.ps1` | Makes the dev TLS certificates in `data\certs` (a private CA plus a server certificate). `run-local.ps1 -Tls` calls it |
| `demo.ps1 <scenario>` | Injects one live scenario, prints the expected result and what the SaaS did. `-List` shows them all |

## First run

```
pip install -r collector\requirements.txt -r saas\requirements.txt
.\scripts\run-local.ps1
```

If your default `python` lacks the dependencies, point `$env:PYTHON` at one that has them. PostgreSQL is found under `C:\Program Files\PostgreSQL`, or set `$env:PG_BIN`. Logs are in `data\logs`.

## TLS (`-Tls`)

```
pip install -r scriptsequirements.txt        # cryptography, for the dev certificates
.\scriptsun-local.ps1 -Tls
.\scripts\demo.ps1 tls
```

With `-Tls` the SaaS replicas serve HTTPS and the collector sends over HTTPS with `REQUIRE_TLS=1`, trusting only the dev CA. The collector always verifies the server certificate and name; there is no switch to turn that off, and TLS 1.2 is the minimum. `demo.ps1 tls` shows plain HTTP refused, HTTPS working, a different CA rejected and a tampered body returning 401.

Collector settings: `SAAS_URL` (https), `SAAS_CA_FILE` (the CA to trust), `REQUIRE_TLS=1` (refuse to start if the URL is not https). These certificates are for development only. Production uses the platform's real PKI, and mTLS would add client certificates on top of the key and signature the collector already sends.

## Real host telemetry

On by default. The collector reads this machine's CPU, memory, disk and network bandwidth every 2 seconds, and probes the SaaS path (TCP connect time and failed connects) plus any service you name. Check what it is measuring at `http://127.0.0.1:8101/local/host`.

| Setting | Meaning | Default |
|---|---|---|
| `HOST_TELEMETRY` | `0` turns it off (`run-local.ps1 -NoHostTelemetry`) | on |
| `PROBE_TARGETS` | extra `host:port` paths to probe, comma separated | the SaaS |
| `SERVICE_CHECKS` | `name=host:port,...` reported as `service_up` | none (run-local sets the SaaS and Postgres) |
| `DISK_PATHS` | paths to watch; the fullest one is reported | the system drive or `/` |
| `SOURCE_TZ` | IANA timezone name sent with events, e.g. `Asia/Kolkata` | `UTC` |
| `HOST_LABEL` | the name this host is known by locally | the machine's hostname |

Real host names, IPs and ports stay on the collector. Each host, probe target and service is sent as its own pseudonymous source. "Packet loss" is the share of failed TCP connection attempts, not an ICMP measurement: it tracks a degrading link but is a different thing, and it works where ping is blocked.

## Scenarios

`tls`, `secret`, `failed-logins`, `cpu-spike`, `latency`, `packet-loss`, `disk`, `alert-storm`, `outage`, `delivery`, `remediation`.

- Run `python simulator\generator.py --seconds 120` (or leave `run-local.ps1`'s simulator running) first, so the SaaS has a baseline.
- `outage` cuts the collector's link, buffers, reconnects and then proves zero loss by comparing payload ID sets.
- `delivery` posts a duplicate, an out-of-order event and a same-ID-different-body payload straight to the SaaS.
- Scenarios on the same host within about 2 minutes join one incident, because correlation is per source and time window.

## Known limits

- Nothing here is production setup: static dev credentials, plain HTTP, one local database.
- `run-local.ps1` has no load balancer, so the collector talks to replica 1 only (the failover proxy is task E12).
- TLS here is server-authenticated only (no client certificates) and uses a throwaway CA.
- With host telemetry on, the real machine reports alongside any simulated hosts. Use `-NoSimulator` to see only the real data.
