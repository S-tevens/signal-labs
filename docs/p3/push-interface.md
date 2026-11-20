# Pushing a stream to Signal Labs: interface for the organizers

This is the page to hand over. You asked us to choose the most fitting way to receive the stream; this is it. Send in whatever shape you already have: we read it, we do not ask you to convert.

## Where and how to authenticate

Run `.\scripts\push-info.ps1` on our machine for the addresses and token. Replace `<collector>` and `<token>` below.

| Method | Address | Notes |
|---|---|---|
| **HTTP POST, any format** (recommended) | `http://<collector>:8101/ingest` | A body of lines, one JSON object, a JSON array, or NDJSON. `Content-Encoding: gzip` is accepted. Up to 8 MiB per request |
| InfluxDB line protocol | `POST http://<collector>:8101/write` (or `/api/v2/write`) | Telegraf's `influxdb` / `influxdb_v2` output works as is. Answers 204 |
| OpenTelemetry metrics | `POST http://<collector>:8101/v1/metrics` | OTLP/HTTP **JSON** (an `otlphttp` exporter with `encoding: json`). Gauge and sum points are read; histograms are skipped. Protobuf is refused with a message |
| Syslog | UDP `<collector>:5514` or TCP `<collector>:5515` | One message per line (RFC3164 or RFC5424) |

Authentication for HTTP: `Authorization: Bearer <token>`, or `Authorization: Token <token>`, or `X-Ingest-Token: <token>`, or HTTP Basic with the token as the password (any username). Syslog over UDP/TCP carries no token, so we limit who may send by source address. Wrong or missing token: `401`. Source not allowed: `403`. Too large: `413`. Success: `200` with `{"received": N, "summary": {...}}`.

## What to put in the data

Nothing is required except that it carries a **host or source name**, a **metric name and number**, and ideally a **time**. All of these work without any change on your side:

```
{"ts":"2026-11-21T10:00:01Z","host":"web-1","metric":"cpu_pct","value":42.5}        one JSON object per line
host=web-1 metric=latency_ms value=180 ts=2026-11-21T10:00:01Z                       key=value
{"timestamp":1795214000000,"hostname":"web-1","cpu_usage":42.5,"mem_used_pct":61}   one column per metric
{"@timestamp":"...","host":{"name":"web-1"},"system":{"cpu":{"total":{"pct":0.42}}}} nested (Elastic, OTel, Telegraf)
cpu_pct{instance="web-1:9100"} 42.5 1795214000000                                    Prometheus text
cpu,host=web-1 usage_user=42.5 1795214000000000000                                   InfluxDB line protocol
<38>1 2026-11-21T10:00:01Z web-1 sshd 411 - - Failed password for root from 203.0.113.9
```

- **Metrics we use** (other names are mapped by configuration, so tell us your names if they differ): CPU, memory and disk use in percent, bandwidth in Mbit/s, latency in milliseconds, packet loss in percent, and service or connectivity up/down (1 or 0). Units that differ (a ratio 0 to 1, seconds, kilobits) are converted from the mapping file.
- **Time**: ISO-8601 (UTC assumed when there is no zone), or epoch seconds, milliseconds, microseconds or nanoseconds. A record with no time is stamped on arrival.
- **Logs and security events**: send them as text lines. A failed-login line is counted locally and only the count can leave. The text itself never leaves.
- **Injected faults**: just send the spike as ordinary values for the affected host (for example CPU 97 for a few windows). There is nothing to flag.

## What happens to it

Everything you send is parsed and kept on the collector (our "customer environment"). Secrets and personal data are detected there. Only allow-listed metadata, summarised per time window, with hosts replaced by pseudonymous IDs, is sent on to the platform. Raw lines, usernames, addresses and free text never leave. Unknown fields are dropped and counted, never guessed.

## Examples

```
curl -X POST http://<collector>:8101/ingest -H "Authorization: Bearer <token>" -d "host=web-1 metric=cpu_pct value=42"

Invoke-RestMethod -Method Post -Uri http://<collector>:8101/ingest -Headers @{Authorization="Bearer <token>"} -Body '{"host":"web-1","metric":"cpu_pct","value":42}'

import requests
requests.post("http://<collector>:8101/ingest", headers={"Authorization": "Bearer <token>"}, data='{"host":"web-1","metric":"cpu_pct","value":42}')
```

Telegraf (`telegraf.conf`):

```
[[outputs.influxdb]]
  urls = ["http://<collector>:8101"]
  database = "telegraf"
  skip_database_creation = true
  http_headers = {"Authorization" = "Bearer <token>"}
```

OpenTelemetry Collector:

```
exporters:
  otlphttp:
    metrics_endpoint: http://<collector>:8101/v1/metrics
    encoding: json
    headers: {Authorization: "Bearer <token>"}
```

Fluent Bit:

```
[OUTPUT]
    Name   http
    Match  *
    Host   <collector>
    Port   8101
    URI    /ingest
    Format json_lines
    Header Authorization Bearer <token>
    compress gzip
```

rsyslog: `*.* @<collector>:5514` (UDP) or `*.* @@<collector>:5515` (TCP).

## Limits and honest notes

- The link is plain HTTP on the local network: the token and the data cross it unencrypted. Use it on a trusted network, or ask us to put the collector behind TLS.
- UDP and TCP syslog carry no token. Restrict the senders with `INGEST_ALLOW` (for example `INGEST_ALLOW=10.0.0.0/24`), which also applies to HTTP.
- Binary protocols (Kafka, MQTT, NetFlow, SNMP traps, OTLP protobuf) are not read; send a text form instead.
- Counters (monotonic totals) are read as the number sent; send rates or gauges for the best result.
