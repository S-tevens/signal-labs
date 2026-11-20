# Connecting the organizers' stream

Status: **ready to connect, not yet connected.** Everything on our side is in place so that connecting takes minutes; when it is connected, the mandatory item "shared organizer telemetry stream" can be ticked, with the evidence this page asks you to keep.

## What the organizers have told us, and how we answer it

This is all we have been given: (1) the traffic format can be anything, so that teams can work with accurate data and optimise; (2) the SaaS can be uniform, central and highly available. No address, token, sample or schema has been shared.

- **"Any format"**: the collector does not assume one. It reads NDJSON, flat and nested JSON (Elastic, OpenTelemetry, Telegraf and Datadog shapes, lists of `{name, value}` objects), key=value, RFC3164 and RFC5424 syslog, CSV with a header, Prometheus text, InfluxDB line protocol and plain text, with names, units and times set in `collector/mapping.yaml` rather than in code. Anything it cannot map is dropped before the pipeline and counted, never guessed.
- **"Uniform, central, highly available SaaS"**: one entry point (a failover proxy) in front of two stateless replicas sharing one Postgres, with row-level tenant isolation and idempotent ingest. Killing a replica loses nothing (`demo.ps1 failover`). It is a single-machine demonstration of the design, not a multi-site deployment.

## Decided: the stream is pushed to us, and we chose the interface

The organizers confirmed they push the stream to us and said to use whatever is most fitting. So we define the interface: HTTP POST in any format as the main route, plus InfluxDB line protocol (Telegraf), OpenTelemetry JSON and syslog for the tools they might already run. Start the collector with `.\scripts\run-local.ps1 -AcceptPush`, run `.\scripts\push-info.ps1` for the addresses and token, and hand over [push-interface.md](push-interface.md). `.\scripts\demo.ps1 push` proves it from the network side (12 checks). The pull settings below are for a case where they change their mind.

## What to get from the organizers (one question)

"How do we receive the stream: do you push it to us, or do we connect to you? Give us the address, any token or key, and about 30 sample lines." Then:

| They say | We do |
|---|---|
| "We send to you" over HTTP POST | Point them at `POST http://<collector>:8101/ingest` (lines or JSON objects in the body). Nothing to configure |
| "We send syslog over UDP" or "lines over TCP" | `UDP_SYSLOG_PORT=5514` or `TCP_LINES_PORT=5515` (add `ADAPTER_BIND=0.0.0.0` if they are on another machine) |
| "Read this file or folder" | `FOLLOW_FILES=C:\path\a.log,C:\path\b.csv` (add `FOLLOW_FROM_START=1` to include what is already in the file) |
| "Connect to this URL" (HTTP, JSON lines or server-sent events) | `STREAM_URL=https://host/path` and, if needed, `STREAM_AUTH="Authorization: Bearer <token>"` |
| "Poll this REST endpoint" (a JSON array or lines) | `STREAM_URL=...` with `STREAM_POLL_S=2` |
| "Connect to this TCP port" | `STREAM_TCP=host:port` |
| "Subscribe on this WebSocket" | `STREAM_WS=wss://host/path` |

Set the variables before starting the collector (`$env:STREAM_URL = "..."` in PowerShell, then `.\scripts\run-local.ps1`). Pulled streams reconnect by themselves with a growing delay. A private CA is trusted with `STREAM_CA_FILE`. The auth value is never logged or shown, and the address is displayed without its key or query string.

## Step 1: check a sample first (two minutes, nothing is sent)

Save the sample lines in a file and run:

```
.\scripts\stream-check.ps1 sample.txt
```

It shows, for each line, the format found, the host, the metric and value after our aliases and unit conversions, whether a time could be read, and which sensitive patterns were seen (they stay local). It lists anything that did not map and the exact lines to add to `collector\mapping.yaml` (for example `net_rx_kbps: {name: bandwidth_mbps, scale: 0.001}`), then ends with a verdict: **READY**, **NEEDS MAPPING** or **NOTHING USABLE**. Edit the mapping file, rerun, repeat until READY. No code changes are needed for names, units, time formats or field names.

Supported without any work: NDJSON; nested JSON read as dotted keys (`system.cpu.total.pct`, with ECS, Telegraf and OpenTelemetry names pre-mapped); a list of objects under one resource (one record each, sharing its host and time); key=value; RFC3164 and RFC5424 syslog; CSV with a header line; Prometheus text exposition (host from the `instance` label); InfluxDB line protocol (host from the `host` tag); plain text; one record per metric column; time as ISO text, epoch seconds, milliseconds, microseconds or nanoseconds, or a handful of date formats (more are one line in the mapping).

## Step 2: connect it and watch

Start the stack. In the egress panel (`http://127.0.0.1:8101/local/ui`) the Pipeline stages box has an **Input streams** row: the stream's address, state (connected or retrying), the number of lines received and the last error. The same data is at `GET /local/stream`. Check that:

1. the state is `connected` and the line count rises;
2. received, aggregated and queued counts in the stages box add up (the two tick lines);
3. payloads appear in the panel with the standard metric names, and a record that contains a secret shows it highlighted locally and absent from the payload;
4. the dashboard shows the collector sending, with a real health state.

If the dropped count is large, a metric name or unit is unmapped: rerun `stream-check.ps1` on a fresh sample and extend the mapping.

## Step 3: keep the evidence

- `.\scripts\trace.ps1 --latest` follows one real record from the stream to the platform and its incident.
- `.\scripts\verify.ps1` confirms the egress log equals what the platform stored and that planted canary secrets reach nowhere.
- `.\scripts\measure.ps1` and `.\scripts\scenario-check.ps1` rerun the timing and scenario checks. They use the simulator for injected faults, so for the organizers' injected scenarios record what you observe against what they announced (the scenario table in `docs/phase-4.md` section 4 is the template).
- Note in the rehearsal record: the stream's address type, the timestamp field and its unit, any time-source difference between their clock and ours, and the sample size.

## What is proven and what is not

Proven with a stand-in: `.\scripts\demo.ps1 stream` starts a mock authenticated feed in a format we had never seen (different field names, units in kilobits and seconds, epoch milliseconds, extra fields, embedded secrets), a collector pulls it, and the platform stores the result: 7 checks, covering the connection, the mapping by configuration only, the unit conversions, secrets staying local, and delivery. That demonstrates the path, not the organizers' real stream. Nothing here has been run against it.

Limits: pulled streams are read as text. Binary protocols (Kafka, MQTT, SNMP traps, NetFlow) are not supported; if the organizers use one, the quickest route is to ask for a text export or a bridge, because a new adapter would be new code. Clock differences between their machine and ours affect any timing measurement; agree a time source first.
