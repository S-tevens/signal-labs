# Scripts

Everything runs locally on Windows PowerShell with dev credentials. No Docker.

| Script | What it does |
|---|---|
| `run-local.ps1` | Starts Postgres (port 5433), runs the migration, then two SaaS replicas, the collector, the simulator and the dashboard. Flags: `-Tls`, `-NoSimulator`, `-NoHostTelemetry`, `-NoProxy`, `-NoDashboard`, `-Restart`, `-Status` |
| `lb.py` | The failover proxy that `run-local.ps1` puts in front of the two replicas (port 8080). Round robin, exact request bytes, automatic failover and recovery. Run it by hand with `python scripts\lb.py --help` |
| `stop-local.ps1` | Stops everything it started (`-KeepDb` leaves Postgres running) |
| `gen-certs.ps1` | Makes the dev TLS certificates in `data\certs` (a private CA plus a server certificate). `run-local.ps1 -Tls` calls it |
| `demo.ps1 <scenario>` | Injects one live scenario, prints the expected result and what the SaaS did. `-List` shows them all |

## First run

```
pip install -r collector\requirements.txt -r saas\requirements.txt
.\scripts\run-local.ps1
```

If your default `python` lacks the dependencies, point `$env:PYTHON` at one that has them. PostgreSQL is found under `C:\Program Files\PostgreSQL`, or set `$env:PG_BIN`. Logs are in `data\logs`.

## Failover proxy

`run-local.ps1` starts `lb.py` on port 8080, and the collector, dashboard and demo scenarios all enter the SaaS through it. It forwards the exact request bytes (the collector's HMAC signs the body, so any change would be a 401), retries on the other replica when a connection fails or a replica answers 502, 503 or 504, and passes real answers (200, 401, 422, ...) through without retrying. A background check brings a replica back when `/healthz` answers again. It also terminates TLS when the stack runs with `-Tls`, and talks to the replicas over verified TLS.

```
.\scripts\demo.ps1 failover          # kills replica 1 mid-stream, then proves zero loss by payload ID set
curl http://127.0.0.1:8080/_lb/status   # which replicas are up, requests served, failovers (local only)
```

Retrying a POST is safe because the SaaS de-duplicates by payload ID, so a request that was processed but whose reply was lost is reported as a duplicate, not stored twice. After the failover demo, restore replica 1 with `.\scripts\run-local.ps1 -Restart` (the database is kept). `-NoProxy` skips the proxy and sends straight to replica 1.

Limits: the proxy is one process and so a single point of failure itself, it cannot fail over a stream that breaks half-way (clients reconnect), and health is polled rather than pushed. It is a demo tool, not production load balancing.

## Local egress proof panel

Open `http://127.0.0.1:8101/local/ui` (collector, this machine only). Pick a payload to see, side by side, the raw records that stayed local (secrets highlighted) and the exact payload that left, with each field's marking. A leak check searches the payload text for every sensitive value found in the raw records and reports whether any appear.

```
.\scripts\demo.ps1 secret            # creates records with passwords, tokens, keys and emails to look at
```

- The `/local/*` views answer only requests from this machine (a 403 otherwise). Set `LOCAL_ALLOW_REMOTE=1` only if you put your own authentication in front.
- Never proxy this page through the SaaS or expose it beyond the customer network.
- Log text is attacker-controlled, so the page never turns data into markup (text nodes only, no `innerHTML`) and is served under a strict content-security policy. A test fails if that changes.
- `GET /local/lineage/<payload_id>` is the same data as JSON: the payload, its raw records, the highlighted spans and the markings.

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

`failover`, `tls`, `secret`, `failed-logins`, `cpu-spike`, `latency`, `packet-loss`, `disk`, `alert-storm`, `outage`, `delivery`, `remediation`.

- Run `python simulator\generator.py --seconds 120` (or leave `run-local.ps1`'s simulator running) first, so the SaaS has a baseline.
- `outage` cuts the collector's link, buffers, reconnects and then proves zero loss by comparing payload ID sets.
- `delivery` posts a duplicate, an out-of-order event and a same-ID-different-body payload straight to the SaaS.
- Scenarios on the same host within about 2 minutes join one incident, because correlation is per source and time window.

## Known limits

- Nothing here is production setup: static dev credentials, plain HTTP, one local database.
- The failover proxy and the Postgres database are each still a single point of failure. A replicated database is out of scope here.
- TLS here is server-authenticated only (no client certificates) and uses a throwaway CA.
- With host telemetry on, the real machine reports alongside any simulated hosts. Use `-NoSimulator` to see only the real data.
