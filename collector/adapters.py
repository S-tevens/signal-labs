"""Input adapters (E16): ways to get a stream in besides POST /ingest.

    UDP_SYSLOG_PORT=5514     one or more lines per datagram
    TCP_LINES_PORT=5515      newline-delimited lines on a connection
    FOLLOW_FILES=a.log,b.csv follow files like `tail -F` (new lines only, unless FOLLOW_FROM_START=1)

All feed the same pipeline as /ingest, so parsing, mapping, redaction and the allow-list apply identically. They are
unauthenticated and bind to ADAPTER_BIND (127.0.0.1 by default): put them on a trusted network only.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .config import Config
from .pipeline import Pipeline
from .pull import PullAdapters

log = logging.getLogger("collector.adapters")


class _Udp(asyncio.DatagramProtocol):
    def __init__(self, pipeline: Pipeline, max_bytes: int):
        self.pipeline, self.max_bytes = pipeline, max_bytes

    def datagram_received(self, data: bytes, addr) -> None:
        if len(data) > self.max_bytes:
            self.pipeline.counters["oversize"] += 1
            return
        self.pipeline.counters["adapter:udp"] += 1
        self.pipeline.process_text(data.decode("utf-8", errors="replace"))


class Adapters:
    def __init__(self, cfg: Config, pipeline: Pipeline):
        self.cfg, self.pipeline = cfg, pipeline
        self._transports: list = []
        self._servers: list = []
        self._tasks: list[asyncio.Task] = []
        self.ports: dict[str, int] = {}
        self.pull = PullAdapters(cfg, pipeline)

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        c = self.cfg
        if c.udp_syslog_port:
            transport, _ = await loop.create_datagram_endpoint(lambda: _Udp(self.pipeline, c.max_line_chars * 4), local_addr=(c.adapter_bind, c.udp_syslog_port))
            self._transports.append(transport)
            self.ports["udp"] = transport.get_extra_info("sockname")[1]
        if c.tcp_lines_port:
            server = await asyncio.start_server(self._tcp_client, c.adapter_bind, c.tcp_lines_port, limit=c.max_line_chars * 2)
            self._servers.append(server)
            self.ports["tcp"] = server.sockets[0].getsockname()[1]
        for path in [p.strip() for p in c.follow_files.split(",") if p.strip()]:
            self._tasks.append(asyncio.create_task(self._follow(Path(path))))
        await self.pull.start()
        if self.ports or self._tasks:
            log.info("input adapters: %s, following %d file(s)", self.ports, len(self._tasks))

    def status(self) -> dict:
        """Where data comes in from, for the egress panel: listeners, followed files and pulled streams."""
        return {"listening": self.ports, "following": [p.strip() for p in self.cfg.follow_files.split(",") if p.strip()], "pulling": self.pull.status()}

    async def stop(self) -> None:
        await self.pull.stop()
        for t in self._tasks:
            t.cancel()
        for t in self._transports:
            t.close()
        for s in self._servers:
            s.close()

    async def _tcp_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        state: dict = {}
        try:
            while True:
                try:
                    line = await reader.readline()
                except (ValueError, asyncio.LimitOverrunError):  # a line over the limit: drop the connection, count it
                    self.pipeline.counters["oversize"] += 1
                    break
                if not line:
                    break
                self.pipeline.counters["adapter:tcp"] += 1
                self.pipeline.process_text(line.decode("utf-8", errors="replace"), state)
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()

    async def _follow(self, path: Path) -> None:
        """tail -F: survives the file not existing yet, truncation and rotation (a smaller or replaced file)."""
        state: dict = {}
        pos, inode, carry = None, None, b""
        while True:
            try:
                stat = path.stat()
                if inode is not None and (stat.st_size < (pos or 0) or (stat.st_ino and stat.st_ino != inode)):
                    pos, carry = 0, b""  # rotated or truncated: read the new file from its start
                if pos is None:
                    pos = 0 if self.cfg.follow_from_start else stat.st_size
                inode = stat.st_ino
                if stat.st_size > pos:
                    chunk = await asyncio.to_thread(_read_from, path, pos, 1 << 20)
                    pos += len(chunk)
                    data = carry + chunk
                    *lines, carry = data.split(b"\n")
                    if len(carry) > self.cfg.max_line_chars * 4:
                        self.pipeline.counters["oversize"] += 1
                        carry = b""
                    if lines:
                        self.pipeline.counters["adapter:file"] += len(lines)
                        self.pipeline.process_text(b"\n".join(lines).decode("utf-8", errors="replace"), state)
                    continue
            except OSError:
                if pos is None:
                    pos = 0  # not there yet: when it appears, read it from the start
            await asyncio.sleep(0.5)


def _read_from(path: Path, pos: int, limit: int) -> bytes:
    with open(path, "rb") as f:
        f.seek(pos)
        return f.read(limit)
