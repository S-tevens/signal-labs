# Scripts

Everything runs locally on Windows PowerShell with dev credentials. No Docker.

| Script | What it does |
|---|---|
| `run-local.ps1` | Starts Postgres (port 5433), runs the migration, then two SaaS replicas, the collector, the simulator and the dashboard. Flags: `-Tls`, `-Profile default|realtime`, `-NoSimulator`, `-NoHostTelemetry`, `-NoProxy`, `-NoDashboard`, `-Restart`, `-Status` |
| `push-info.ps1` | Prints the addresses and token to hand the organizers so they can push their stream (start the collector with `run-local.ps1 -AcceptPush` first). See [../docs/p3/push-interface.md](../docs/p3/push-interface.md) |
| `stream-check.ps1` | Dry-runs a sample of the organizers' stream through the collector's parsers and mapping and tells you what to map (nothing is sent). See [../docs/p3/organizer-stream.md](../docs/p3/organizer-stream.md) |
| `reset-demo.ps1` | Starts the demo from a clean slate (fresh database and collector store, development users kept): no leftover test collectors, everything live. `-AcceptPush`, `-NoSimulator` pass through |
| `recover.ps1` | Checks the whole stack and fixes a link left down or a hold left on; `-Restart` restarts it. See [../docs/p4/demo-runbook.md](../docs/p4/demo-runbook.md) |
| `bundle-evidence.ps1` | Zips the evidence, guides, settings and the commit into `data\evidence-bundle-<time>.zip`, refusing if anything looks like a credential |
| `scenario-check.ps1` | A normal baseline and seven injected scenarios in parallel, with expected versus actual, missed, extra and false alerts counted, and the window and denominator stated (about 2.5 minutes) |
| `trace.ps1` | Traces one payload from the raw record through the outgoing payload and the platform's stored copy to its incident and recommendation. PASS or FAIL per hop, secrets masked |
| `rehearse.ps1` | Runs every scenario and the proof checks in judge order with pauses, and writes a pass/fail table with timestamps. See [Rehearsal](#rehearsal) |
| `open-demo.ps1` | Opens the egress panel and the dashboard side by side |
| `verify.ps1` | Proof tools: the egress log equals what the SaaS stored, and planted canary secrets appear nowhere on the platform. PASS or FAIL. See [Proving the privacy claim](#proving-the-privacy-claim) |
| `measure.ps1` | Measures the real-time targets and delivery from timestamps and writes an evidence file. See [Measuring the real-time targets](#measuring-the-real-time-targets) |
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

## Measuring the real-time targets

```
.\scripts\measure.ps1                  # everything, about 6 minutes
.\scripts\measure.ps1 latency          # collection to dashboard, p95 <= 10 s
.\scripts\measure.ps1 alert anomaly    # threshold breach and baseline deviation to alert, <= 15 s
.\scripts\measure.ps1 offline          # collector killed to Poor, <= 60 s
.\scripts\measure.ps1 delivery         # forced outage, sent IDs vs received IDs
```

Start the stack with `run-local.ps1 -Tls -NoSimulator` first for the cleanest numbers. Each test sends records timestamped *now* from its own unique host (never backdated), so it is not skewed by old data or other traffic, and each result is PASS or FAIL against its target. A run writes `docs\p3\evidence\measure-<time>.md` (the table, with the settings used) and a `.json` with every raw timestamp.

- **Dashboard** is measured two ways. The *API* path polls the platform twice a second, the earliest the data could be shown. The *dashboard path* does what the real dashboard does when the platform pushes a snapshot: fetches the fleet, incidents, proof and four metric series.
- **Collection latency** is reported from the payload's newest record and from the start of its window. The verdict uses the strict one (window start).
- **Offline** is measured from the last heartbeat, and from the moment the collector was killed (a hard kill, no goodbye).
- **Delivery** cuts the platform link, keeps sending, restores the link and compares payload ID sets. Duplicates are checked independently (repeated IDs in the platform's listing), not from the platform's own counter.
- All timestamps are on one machine and so one clock. Results from earlier runs are in [docs/p3/evidence/SUMMARY.md](../docs/p3/evidence/SUMMARY.md).

## Timing profiles

The collector's timing is one preset, chosen with `PROFILE` (or `run-local.ps1 -Profile`). An explicit `WINDOW_S`, `GRACE_S`, `FLUSH_INTERVAL_S`, `SEND_INTERVAL_S` or `HEARTBEAT_INTERVAL_S` always wins over the preset, and an unknown profile name stops the collector. The profile in use is shown at `http://127.0.0.1:8101/local/timing` and recorded in every evidence file.

| Setting | `default` | `realtime` (the runner's default) |
|---|---|---|
| Aggregation window | 5 s | 2 s |
| Grace for late events | 2 s | 1 s |
| Window flush check | 1 s | 0.5 s |
| Send interval | 1 s | 0.25 s |
| Heartbeat | 10 s | 5 s |

Measured result: at `default` the strict collection-to-dashboard p95 was 10.2 to 11.1 s (over the 10 s target); at `realtime` it was 5.95 s. The cost is roughly 2.5 times more payloads per collector. The failed-login burst threshold is per window, so a shorter window raises the effective rate threshold from 1 to 2.5 failures per second.

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

**Hold and release.** The strip at the top shows the link state, how many payloads are waiting, how long the oldest has waited and the last error. **Hold sending** stops payloads leaving: they stay in the outbox, visible in the list as `pending`, with the SHA-256 of their exact bytes. **Release** lets them go under the same IDs. A hold ends by itself after 5 minutes. Heartbeats keep flowing during a hold, so the platform still sees the collector as alive. Each payload shows its digest and, once delivered, its sent time.

```
.\scripts\demo.ps1 hold             # holds, injects a secret-bearing record, shows it pending, releases it, checks ID and digest
```

- The digest is fixed when the payload is queued. If the stored body ever differs from it, that payload is not sent and is closed out as rejected, with the reason on the strip.
- Hold and release answer only to this machine, only with a Host of `localhost`, `127.0.0.1` or `::1`, and only with an `X-Requested-With: local-ui` header that the page sends. Another site open in your browser cannot set that header without a preflight the collector never answers.

The panel's **Pipeline stages** box (and `GET /local/stages`) shows each stage's count since the collector started and two checks that the counts add up: every received record ends as dropped, oversize or aggregated, and every closed window ends as queued, failed schema or blocked by policy. The full demo, in order, is in [../docs/p3/collector.md](../docs/p3/collector.md).

## Rehearsal

```
.\scripts
ehearse.ps1                    # 14 steps, about 8 minutes, 10 s between steps
.\scripts
ehearse.ps1 -Pause 20          # longer pauses so incidents separate
.\scripts
ehearse.ps1 -WithMeasure       # also the timing measurements (about 6 more minutes)
.\scripts
ehearse.ps1 -Only secret,hold  # just these steps
.\scripts\open-demo.ps1                   # egress panel left, dashboard right
```

Needs the stack running. A step is FAIL on a non-zero exit or a failure word in its output, PASS if it printed a verdict, and "ran" if it only shows you something to look at. The run writes `docs\p3\evidence
ehearsal-<time>.md` with the table and every step's output, and exits 1 if anything failed.

## Proving the privacy claim

```
.\scriptserify.ps1            # both checks
.\scriptserify.ps1 match      # the egress log equals what the SaaS stored
.\scriptserify.ps1 canary     # planted secrets appear nowhere on the platform
```

Exit code 0 = PASS, 1 = FAIL, 2 = INCOMPLETE (a required check could not run, so nothing is claimed). Evidence goes to `docs\p3\evidenceerify-<time>.md` and `.json`.

- **Match** compares the newest 300 payloads the collector reports as sent with the observation the platform stored under the same ID, field by field (the platform widens timestamps to microseconds; that is ignored). It reports payloads missing at the platform, any field that differs, a changed digest in the egress log, and platform payloads the collector never sent.
- **Canary** plants eight fake secrets unique to the run (password, API key, JWT, email, AWS key, username, host name, free text) in four log formats, waits for the payloads to be delivered, then searches the collector's egress log, 100+ platform API responses, every table of the platform database for all tenants (read with the admin role through `psql`) and the platform logs, for each canary in plain, lower-case, JSON-escaped, URL-encoded and base64 forms.
- **Controls that keep a PASS honest:** the scanner must find a canary it is shown; every canary must appear in the collector's local raw store (so it was really received); the run must have produced payloads; and every surface scanned must contain a known real value (so an empty or unreadable surface cannot pass). If the database cannot be read the result is INCOMPLETE, not PASS.
- Limits: it proves these canaries did not travel, not that no other secret ever could. The database scan needs `psql` (found automatically, or set `PG_BIN`); `ADMIN_DATABASE_URL` overrides the default local connection.

## TLS (`-Tls`)

```
pip install -r scripts
equirements.txt        # cryptography, for the dev certificates
.\scripts
un-local.ps1 -Tls
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

## Retention and limits

A collector cannot be made to fill its disk. Caps apply as data is written (a timer also deletes expired data every 5 minutes). Check what is stored and what has been dropped at `http://127.0.0.1:8101/local/retention`.

| Setting | Meaning | Default |
|---|---|---|
| `RAW_RETENTION_S` | raw records are deleted after this long | 86400 (1 day) |
| `OUTBOX_RETENTION_S` | delivered or rejected transfer records are deleted after this long | 604800 (7 days) |
| `RAW_MAX_ROWS` | keep at most this many raw records (newest) | 500000 |
| `MAX_DB_BYTES` | cap on live data in the local database | 1 GiB |
| `OUTBOX_MAX_PENDING` | cap on undelivered payloads; the **oldest** are dropped first, counted and reported | 100000 |
| `MAX_LINE_CHARS` | a longer line is never parsed (a short marker is kept) | 65536 |
| `MAX_INGEST_BYTES` | a larger request body is refused with 413 | 8 MiB |
| `RETENTION_INTERVAL_S` | how often the retention job runs | 300 |

## Enrolling a collector

A collector can register itself instead of being given keys:

```
# an admin creates a one-time token for it (POST /v1/enrollment-tokens, admin role), then on the new machine:
$env:ENROLL_TOKEN = "<token>"; $env:ENROLL_TENANT = "t-acme"
$env:SAAS_URL = "https://<saas>"; $env:SAAS_CA_FILE = "<ca.pem>"
python -m uvicorn collector.main:app --port 8101      # enrolls on first start, then reports
# or enroll without starting: python -m collector.enroll --saas-url https://<saas> --ca <ca.pem> --tenant t-acme --token-file token.txt
```

The token only ever travels over verified HTTPS (plain HTTP is refused). The collector receives its own key and signing secret once, creates its own pseudonym secret locally, and saves them to `<DATA_DIR>\credentials.json`, readable only by its owner. After that it uses those instead of the built-in dev defaults, and `http://127.0.0.1:8101/local/identity` shows `credentials: enrolled` (it never shows a secret). A damaged credentials file stops the collector instead of letting it run on defaults. The token is single-use; if saving fails after the platform issued credentials, ask for a new token. `--force` enrolls again. Not built: rotating or revoking credentials from the collector side.

## Bringing in a stream: formats, adapters, replay

The collector takes `POST /ingest` and, when switched on, three more inputs. All feed the same pipeline, so mapping, redaction and the allow-list apply identically. They are unauthenticated and bind to `ADAPTER_BIND` (default `127.0.0.1`), so use them on a trusted network only.

```
UDP_SYSLOG_PORT=5514   TCP_LINES_PORT=5515   FOLLOW_FILES=C:\logs.log,C:\logs.csv   FOLLOW_FROM_START=1
```

- **Formats:** NDJSON, key=value, RFC3164 syslog, CSV (a header line sets the columns for the lines after it) and plain text. A row can carry several metrics, one per column.
- **`collector/mapping.yaml`** is where a new format is handled without code: the field names for host, metric name, value, time and message; metric aliases with unit conversion (`cpu_ratio` x 100, `latency_s` x 1000, `mem_free_pct` as 100 minus); extra time formats (epoch seconds, ms, us and ns and ISO are built in). Fields not listed are dropped before anything else sees them. A bad mapping file stops the collector at start. `MAPPING_FILE` points to another file.
- **Samples:** `python simulator\samples.py --list` prints five differently shaped streams (wide NDJSON with epoch ms, CSV with day-first dates, key=value with other field names, syslog failed logins, mixed text with secrets).
- **Replay and timelines:** `python simulator
eplay.py play simulator	imelines\demo.json [--speed 5]` plays a scripted five-minute timeline (steady traffic, CPU spike at 90 s, latency spike at 150 s, failed-login burst at 190 s, SaaS outage 230 to 255 s). The same timeline and seed always build the same recording (`replay.py build ... -o file.jsonl`). Timestamps are always rebased to now, so it is never backdated. A raw log with ISO timestamps also plays; other time formats in raw logs are not rebased.

## Scenarios

`enroll`, `flood`, `failover`, `tls`, `secret`, `hold`, `tenants`, `rbac`, `stream`, `push`, `failed-logins`, `cpu-spike`, `latency`, `packet-loss`, `disk`, `alert-storm`, `outage`, `delivery`, `remediation`.

- Run `python simulator\generator.py --seconds 120` (or leave `run-local.ps1`'s simulator running) first, so the SaaS has a baseline.
- `outage` cuts the collector's link, buffers, reconnects and then proves zero loss by comparing payload ID sets.
- `delivery` posts a duplicate, an out-of-order event and a same-ID-different-body payload straight to the SaaS.
- `enroll` has an admin issue a one-time token, starts a brand-new collector (port 8102, no keys configured) that enrolls itself and starts reporting, shows the platform seeing it online, and shows the same token refused a second time. Needs the stack from `run-local.ps1` (it includes a dev admin token); use `-Tls` so the token and credentials travel encrypted.
- `flood` starts a collector (port 8103) with tight limits and no reachable platform, sends 40,000 lines, an oversize line and a 3 MiB request, then shows the caps holding, the counted losses and the loss event.
- `push` pushes to the collector through this machine's network address the way the organizers would: token required, HTTP lines, a JSON array, gzip, Telegraf's InfluxDB output, OpenTelemetry JSON, a secret kept local, delivery to the platform (12 checks). Needs `run-local.ps1 -AcceptPush`.
- `stream` stands in for the organizers: a mock authenticated feed in an unfamiliar format, pulled by a second collector (port 8104), checked from connection to the stored payload (7 checks).
- `rbac` checks role-based access on the live platform with real sign-ins (admin, operator, viewer and auditor from `data\dev-users.txt`): 28 checks, including a role changed live, a lockout and reset, the last-administrator guard and that refusals are audited with names. See [../docs/p4/security.md](../docs/p4/security.md).
- `tenants` uses a second dev tenant (`t-globex`, key `key-globex-1`, dashboard token `dash-globex`) to check: each token sees only its own fleet, observations and metrics; a cross-tenant object fetch is 404; a payload naming the other tenant or signed with its key is refused; and an extra field, a secret-like summary, an unknown metric and a non-UTC time are each rejected with the platform's reason. Prints PASS or FAIL per check.
- Each payload's `health_state` is now the collector's own verdict (`collector/health.py`, `health.yaml`): the same thresholds and rules as the platform, so a CPU spike is reported Poor by both. A test fails if the two threshold files drift apart.
- The heartbeat carries the collector process's own CPU, memory and data-disk share (`cpu_percent`, `memory_percent`, `disk_percent`, the only names the platform contract allows) and a `config_hash` that fingerprints every non-secret setting plus the policy and mapping files, so it changes when any of them changes. Uptime is not sent: the contract has no field for it.
- `remediation` drives the SaaS action lifecycle on the latest incident: a policy check that refuses an action on a different source, then propose, approve, roll back, the audit trail, and a blocked invalid transition. It is a simulation: nothing is executed.
- Scenarios on the same host within about 2 minutes join one incident, because correlation is per source and time window.

## Known limits

- Nothing here is production setup: static dev credentials, plain HTTP, one local database.
- The failover proxy and the Postgres database are each still a single point of failure. A replicated database is out of scope here.
- TLS here is server-authenticated only (no client certificates) and uses a throwaway CA.
- With host telemetry on, the real machine reports alongside any simulated hosts. Use `-NoSimulator` to see only the real data.
