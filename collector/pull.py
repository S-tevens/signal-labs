"""Pull inputs (E26): connect OUT to a stream the organizers expose, instead of waiting for it to be pushed to us.

    STREAM_URL=https://host/path      an HTTP(S) endpoint. A long-lived response is read line by line (NDJSON, plain lines,
                                      or server-sent events: `data:` lines). STREAM_POLL_S=2 polls it every 2 s instead
                                      (a body that is a JSON array becomes one record per element).
    STREAM_TCP=host:port              a TCP server that writes lines.
    STREAM_WS=wss://host/path         a WebSocket that sends text frames (each may hold one record, several lines or an array).
    STREAM_AUTH="Authorization: Bearer <token>"   a header sent with every request (a bare token becomes a Bearer header).
    STREAM_CA_FILE=ca.pem             trust this CA for https and wss.

Whatever arrives goes through the same pipeline as /ingest, so parsing, mapping, redaction and the allow-list apply
identically. The connection retries with backoff and its state is visible at GET /local/stream and in the egress panel.
The auth header is never logged or shown; the target is shown without credentials or query string.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from .config import Config
from .pipeline import Pipeline

log = logging.getLogger("collector.pull")


def expand(text: str) -> str:
    """A JSON array becomes one JSON object per line; anything else is left alone."""
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except ValueError:
            return text
        if isinstance(data, list):
            return "\n".join(json.dumps(x, separators=(",", ":")) if not isinstance(x, str) else x for x in data)
    return text


def sse_payload(line: str) -> str | None:
    """Server-sent events: keep the `data:` lines, drop event, id, retry and comment lines. Plain lines pass through."""
    if line.startswith(("event:", "id:", "retry:", ":")):
        return None
    return line[5:].strip() if line.startswith("data:") else line


def auth_headers(spec: str) -> dict[str, str]:
    spec = (spec or "").strip()
    if not spec:
        return {}
    if ":" in spec.split(" ", 1)[0] or (": " in spec):
        name, _, value = spec.partition(":")
        return {name.strip(): value.strip()}
    return {"Authorization": spec if spec.lower().startswith(("bearer ", "basic ")) else f"Bearer {spec}"}


def shown(target: str) -> str:
    """The target without credentials or query string."""
    p = urlsplit(target if "://" in target else f"tcp://{target}")
    host = p.hostname or ""
    return f"{p.scheme}://{host}{':' + str(p.port) if p.port else ''}{p.path}"


class Source:
    """One connection and its visible state."""

    def __init__(self, kind: str, target: str):
        self.kind, self.target = kind, shown(target)
        self.state, self.lines, self.reconnects = "connecting", 0, 0
        self.last_data_utc: str | None = None
        self.last_error: str | None = None

    def describe(self) -> dict:
        return {"kind": self.kind, "target": self.target, "state": self.state, "lines_received": self.lines,
                "reconnects": self.reconnects, "last_data_utc": self.last_data_utc, "last_error": self.last_error}


class PullAdapters:
    def __init__(self, cfg: Config, pipeline: Pipeline):
        self.cfg, self.pipeline = cfg, pipeline
        self.sources: list[Source] = []
        self._tasks: list[asyncio.Task] = []

    def _tls(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(cafile=self.cfg.stream_ca_file or None)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    def _feed(self, src: Source, text: str, state: dict) -> None:
        text = expand(text)
        n = sum(1 for line in text.splitlines() if line.strip())
        if not n:
            return
        self.pipeline.process_text(text, state)
        self.pipeline.counters["adapter:pull"] += n
        src.lines += n
        src.last_data_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def start(self) -> None:
        c = self.cfg
        for kind, target, runner in (("http", c.stream_url, self._http), ("tcp", c.stream_tcp, self._tcp), ("websocket", c.stream_ws, self._ws)):
            if target:
                src = Source(kind, target)
                self.sources.append(src)
                self._tasks.append(asyncio.create_task(self._forever(src, runner, target)))
        if self.sources:
            log.info("pulling from: %s", ", ".join(f"{s.kind} {s.target}" for s in self.sources))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    def status(self) -> list[dict]:
        return [s.describe() for s in self.sources]

    async def _forever(self, src: Source, runner, target: str) -> None:
        delay = 1.0
        while True:
            started = time.time()
            try:
                src.state = "connecting"
                await runner(src, target)
                src.last_error = "the stream ended"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # any failure: say what kind, never include the URL or headers
                src.last_error = f"{type(exc).__name__}: {str(exc)[:120]}".replace(target, src.target)
            src.state, src.reconnects = "retrying", src.reconnects + 1
            delay = 1.0 if time.time() - started > 30 else min(30.0, delay * 2)  # a connection that lasted resets the backoff
            await asyncio.sleep(delay)

    async def _http(self, src: Source, url: str) -> None:
        headers = auth_headers(self.cfg.stream_auth)
        verify = self._tls() if url.startswith("https") else True
        state: dict = {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10), verify=verify) as client:
            if self.cfg.stream_poll_s > 0:
                while True:
                    r = await client.get(url, headers=headers)
                    r.raise_for_status()
                    src.state = "connected"
                    self._feed(src, r.text, state)
                    await asyncio.sleep(self.cfg.stream_poll_s)
            async with client.stream("GET", url, headers={"Accept": "text/event-stream, application/x-ndjson, */*", **headers}) as r:
                r.raise_for_status()
                src.state = "connected"
                async for line in r.aiter_lines():
                    payload = sse_payload(line)
                    if payload:
                        self._feed(src, payload, state)

    async def _tcp(self, src: Source, target: str) -> None:
        host, _, port = target.rpartition(":")
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port), limit=self.cfg.max_line_chars * 2), 10)
        state: dict = {}
        src.state = "connected"
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                self._feed(src, line.decode("utf-8", errors="replace"), state)
        finally:
            writer.close()

    async def _ws(self, src: Source, url: str) -> None:
        import websockets

        kwargs = {"additional_headers": auth_headers(self.cfg.stream_auth) or None, "max_size": self.cfg.max_line_chars * 8}
        if url.startswith("wss"):
            kwargs["ssl"] = self._tls()
        state: dict = {}
        async with websockets.connect(url, **kwargs) as ws:
            src.state = "connected"
            async for message in ws:
                self._feed(src, message.decode("utf-8", errors="replace") if isinstance(message, bytes) else message, state)
