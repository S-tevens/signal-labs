"""The push gateway: how the organizers (or any agent) send their stream to the collector.

Endpoints (all POST, all behind the same guard):
    /ingest            lines or JSON in any supported format; a JSON array or NDJSON body is fine; gzip accepted
    /write             InfluxDB line protocol (Telegraf's influxdb output), answers 204
    /api/v2/write      the same, for InfluxDB v2 clients
    /v1/metrics        OpenTelemetry metrics as OTLP/HTTP JSON (protobuf is refused with a clear message)
Also UDP syslog and TCP lines (see adapters.py) when those ports are enabled.

The guard: when INGEST_TOKEN is set every request must carry it, as `Authorization: Bearer <t>` or `Token <t>`, as
`X-Ingest-Token: <t>`, or as the password of HTTP Basic auth (any username), so common agents work without code. When
INGEST_ALLOW is set (comma-separated addresses or networks) only those sources may push, over HTTP, UDP or TCP. Tokens
are compared in constant time and never logged. The local views (/local/*) stay local whatever is configured here.
"""
from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import zlib

from fastapi import HTTPException, Request


def parse_allow(spec: str) -> list:
    nets = []
    for item in [x.strip() for x in (spec or "").split(",") if x.strip()]:
        nets.append(ipaddress.ip_network(item, strict=False))
    return nets


def ip_allowed(nets: list, ip: str) -> bool:
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return any(addr in n for n in nets)


def presented_token(headers) -> str:
    auth = headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() in ("bearer", "token") and value:
        return value.strip()
    if scheme.lower() == "basic" and value:
        try:
            return base64.b64decode(value).decode().partition(":")[2]  # the password
        except (ValueError, UnicodeDecodeError):
            return ""
    return headers.get("x-ingest-token", "").strip()


class PushGuard:
    def __init__(self, token: str, allow: str):
        self.token = token or ""
        self.nets = parse_allow(allow)

    @property
    def open(self) -> bool:
        return not self.token and not self.nets

    def check(self, request: Request) -> None:
        host = request.client.host if request.client else ""
        if not ip_allowed(self.nets, host):
            raise HTTPException(403, "this address may not push to this collector")
        if self.token and not hmac.compare_digest(presented_token(request.headers).encode(), self.token.encode()):
            raise HTTPException(401, "a valid ingest token is required (Authorization: Bearer <token>, or X-Ingest-Token)")


async def read_body(request: Request, limit: int) -> bytes:
    """The request body, stopped at `limit` bytes both on the wire and after gzip, so neither a huge body nor a zip bomb can
    exhaust memory."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"request body over the {limit} byte limit")
    raw, total = bytearray(), 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"request body over the {limit} byte limit")
        raw.extend(chunk)
    encoding = request.headers.get("content-encoding", "").lower()
    if encoding in ("gzip", "x-gzip"):
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            data = d.decompress(bytes(raw), limit + 1)
        except zlib.error:
            raise HTTPException(400, "the body is not valid gzip") from None
        if len(data) > limit or d.unconsumed_tail:
            raise HTTPException(413, f"request body over the {limit} byte limit once decompressed")
        return data
    if encoding not in ("", "identity"):
        raise HTTPException(415, f"Content-Encoding {encoding!r} is not supported; use gzip or none")
    return bytes(raw)


def _attr(attrs: list | None, *names: str):
    for a in attrs or []:
        if a.get("key") in names:
            v = a.get("value", {})
            return v.get("stringValue") or v.get("intValue") or v.get("doubleValue")
    return None


def otlp_to_lines(doc: dict) -> list[str]:
    """OTLP/HTTP JSON metrics -> one JSON line per gauge or sum data point (histograms are skipped). Names go through the
    mapping like any other source, so `system.cpu.utilization` becomes cpu_pct."""
    lines: list[str] = []
    for rm in doc.get("resourceMetrics", []) if isinstance(doc, dict) else []:
        host = _attr(rm.get("resource", {}).get("attributes"), "host.name", "host.id", "service.instance.id", "k8s.node.name", "service.name")
        for sm in rm.get("scopeMetrics", []):
            for m in sm.get("metrics", []):
                points = (m.get("gauge") or m.get("sum") or {}).get("dataPoints", [])
                for dp in points[:5000]:
                    value = dp.get("asDouble", dp.get("asInt"))
                    if value is None:
                        continue
                    row = {"host": _attr(dp.get("attributes"), "host.name", "host") or host or "unknown", "metric": m.get("name"), "value": float(value)}
                    if dp.get("timeUnixNano"):
                        row["ts"] = str(dp["timeUnixNano"])
                    lines.append(json.dumps(row, separators=(",", ":")))
    return lines
