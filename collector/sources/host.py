"""Real host telemetry: CPU, memory, disk, bandwidth from the machine, latency and loss from probes.

Metrics produced (all on the allow-list in collector/schema.py):
    cpu_pct, mem_pct, disk_pct, bandwidth_mbps       the host itself
    latency_ms, packet_loss_pct, connectivity_up     per probe target (network path)
    service_up                                       per configured service check

Honest limits:
  * The probe measures TCP connect time and connect failures, not ICMP. "Loss" here is the share of failed
    connection attempts, which tracks real packet loss on a degrading link but is not the same measurement.
    TCP needs no admin rights and works where ping is blocked.
  * bandwidth_mbps is total bytes in plus out across all interfaces, in megabits per second.
  * Each probe target and service is its own pseudonymous source, so one bad path does not hide behind a healthy host.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from urllib.parse import urlparse

log = logging.getLogger("collector.host")


@dataclass(frozen=True)
class Target:
    host: str
    port: int

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}"


def parse_target(text: str) -> Target:
    host, _, port = text.strip().rpartition(":")
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"expected host:port, got {text!r}")
    return Target(host, int(port))


def parse_targets(spec: str) -> list[Target]:
    return [parse_target(p) for p in spec.split(",") if p.strip()]


def parse_services(spec: str) -> list[tuple[str, Target]]:
    out = []
    for part in spec.split(","):
        if not part.strip():
            continue
        name, sep, target = part.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"expected name=host:port, got {part!r}")
        out.append((name.strip(), parse_target(target)))
    return out


def saas_target(saas_url: str) -> Target | None:
    """The network path to the central platform is always worth watching."""
    u = urlparse(saas_url)
    if not u.hostname:
        return None
    return Target(u.hostname, u.port or (443 if u.scheme == "https" else 80))


def tcp_probe(host: str, port: int, attempts: int, timeout: float) -> tuple[float | None, float]:
    """Return (median connect latency in ms or None if every attempt failed, failure percentage)."""
    times: list[float] = []
    failed = 0
    for _ in range(max(1, attempts)):
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                times.append((time.perf_counter() - start) * 1000.0)
        except OSError:
            failed += 1
    return (round(median(times), 3) if times else None), round(failed / max(1, attempts) * 100.0, 2)


def _default_disk_path() -> str:
    return os.path.abspath(os.sep)


class HostSampler:
    """Turns the machine's current state into normalized records. No I/O besides reading the machine."""

    def __init__(self, cfg, psutil_mod=None, clock=time.time):
        if psutil_mod is None:
            import psutil as psutil_mod  # imported lazily so the collector still starts without psutil
        self.ps = psutil_mod
        self.cfg = cfg
        self.clock = clock
        self.label = cfg.host_label
        self.tz = cfg.source_tz
        self.disks = [p.strip() for p in cfg.disk_paths.split(",") if p.strip()] or [_default_disk_path()]
        targets = parse_targets(cfg.probe_targets)
        default = saas_target(cfg.saas_url)
        if default and default not in targets:
            targets.insert(0, default)
        self.targets = targets
        self.services = parse_services(cfg.service_checks)
        self._net: tuple[float, int] | None = None
        self.last: dict[str, dict] = {}  # latest value per metric and source, for /local/host

    # ---- helpers ----
    def _record(self, host: str, name: str, value: float) -> dict:
        ts = datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec = {"kind": "metric", "ts": ts, "tz": self.tz, "host": host, "name": name, "value": float(value), "format": "host"}
        self.last[f"{host}|{name}"] = {"value": rec["value"], "ts": ts}
        return rec

    def prime(self) -> None:
        """psutil's first CPU reading is meaningless and bandwidth needs a previous sample: take both now."""
        self.ps.cpu_percent(None)
        self._net = (self.clock(), self._net_bytes())

    def _net_bytes(self) -> int:
        n = self.ps.net_io_counters()
        return int(n.bytes_sent + n.bytes_recv)

    # ---- the host itself ----
    def sample_host(self) -> list[dict]:
        out = [
            self._record(self.label, "cpu_pct", self.ps.cpu_percent(None)),
            self._record(self.label, "mem_pct", self.ps.virtual_memory().percent),
        ]
        used: list[float] = []
        for path in self.disks:
            try:
                used.append(self.ps.disk_usage(path).percent)
            except OSError as exc:
                log.warning("disk path %s unreadable: %s", path, exc)
        if used:
            out.append(self._record(self.label, "disk_pct", max(used)))  # the fullest disk is the one that matters
        now, total = self.clock(), self._net_bytes()
        if self._net is not None and now > self._net[0]:
            mbps = max(0.0, (total - self._net[1]) * 8 / (now - self._net[0]) / 1e6)
            out.append(self._record(self.label, "bandwidth_mbps", round(mbps, 3)))
        self._net = (now, total)
        return out

    # ---- network paths and services (slow: run in a thread) ----
    def sample_paths(self) -> list[dict]:
        out: list[dict] = []
        for t in self.targets:
            latency, loss = tcp_probe(t.host, t.port, self.cfg.probe_attempts, self.cfg.probe_timeout_s)
            source = f"{self.label}->{t.label}"
            if latency is not None:
                out.append(self._record(source, "latency_ms", latency))
            out.append(self._record(source, "packet_loss_pct", loss))
            out.append(self._record(source, "connectivity_up", 0.0 if latency is None else 1.0))
        return out

    def sample_services(self) -> list[dict]:
        out = []
        for name, t in self.services:
            latency, _ = tcp_probe(t.host, t.port, 1, self.cfg.probe_timeout_s)
            out.append(self._record(f"{self.label}:{name}", "service_up", 0.0 if latency is None else 1.0))
        return out

    def sample_slow(self) -> list[dict]:
        return self.sample_paths() + self.sample_services()


class HostSource:
    """Feeds the sampler's records into the pipeline on a timer."""

    def __init__(self, cfg, pipeline, sampler: HostSampler | None = None):
        self.cfg = cfg
        self.pipeline = pipeline
        self.sampler = sampler or HostSampler(cfg)
        self.errors = 0
        self.adaptive_mode = 'normal'
        self.adaptive_reason = 'Adaptive sampling disabled' if not cfg.adaptive_telemetry else 'No sustained high host utilization'
        self._normal_samples = 0

    def sampling_interval(self, records: list[dict]) -> float:
        """Optional host-only sampling; no change to event, heartbeat or delivery timing."""
        base=self.cfg.host_interval_s
        if not self.cfg.adaptive_telemetry: return base
        values=[r['value'] for r in records if r.get('name') in {'cpu_pct','mem_pct'}]
        if values and max(values)>=80:
            self.adaptive_mode='fast'; self._normal_samples=0
            self.adaptive_reason='CPU or memory reached 80%'
        elif self.adaptive_mode=='fast' and len(values)==2 and max(values)<70:
            self._normal_samples+=1
            if self._normal_samples>=3:
                self.adaptive_mode='normal'; self._normal_samples=0
                self.adaptive_reason='CPU and memory remained below 70% for three samples'
        elif self.adaptive_mode=='fast': self._normal_samples=0
        return min(base,max(.5,base/2)) if self.adaptive_mode=='fast' else base

    def _ingest(self, records: list[dict]) -> None:
        for rec in records:
            self.pipeline.process_record(rec, json.dumps(rec))

    async def run(self) -> None:
        self.sampler.prime()
        next_slow = 0.0
        loop = asyncio.get_running_loop()
        while True:
            interval=self.cfg.host_interval_s
            try:
                records=self.sampler.sample_host()
                self._ingest(records)
                interval=self.sampling_interval(records)
                if loop.time() >= next_slow:
                    next_slow = loop.time() + self.cfg.probe_interval_s
                    self._ingest(await asyncio.to_thread(self.sampler.sample_slow))
            except Exception:  # one bad sample must never stop monitoring
                self.errors += 1
                log.exception("host sampling failed")
            await asyncio.sleep(interval)

    def status(self) -> dict:
        s = self.sampler
        return {
            "host_label_pseudonymized_before_sending": s.label,
            "targets": [t.label for t in s.targets],
            "services": [{"name": n, "target": t.label} for n, t in s.services],
            "disk_paths": s.disks,
            "latest": s.last,
            "errors": self.errors,
            "adaptive_sampling": {"enabled": self.cfg.adaptive_telemetry, "mode": self.adaptive_mode, "reason": self.adaptive_reason, "normal_interval_s": self.cfg.host_interval_s, "fast_interval_s": min(self.cfg.host_interval_s,max(.5,self.cfg.host_interval_s/2)), "scope": "local host CPU/memory sampling only"},
        }
