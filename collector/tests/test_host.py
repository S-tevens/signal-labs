import asyncio
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from collector.config import Config
from collector.outbox import LocalStore
from collector.pipeline import Pipeline
from collector.schema import Payload
from collector.sources.host import HostSampler, HostSource, parse_services, parse_target, parse_targets, tcp_probe


class FakePsutil:
    """Deterministic stand-in for psutil."""

    def __init__(self):
        self.cpu, self.mem, self.disk = 42.0, 61.5, {"/": 70.0}
        self.sent = self.recv = 0

    def cpu_percent(self, interval=None):
        return self.cpu

    def virtual_memory(self):
        return SimpleNamespace(percent=self.mem)

    def disk_usage(self, path):
        if path not in self.disk:
            raise OSError("no such path")
        return SimpleNamespace(percent=self.disk[path])

    def net_io_counters(self):
        return SimpleNamespace(bytes_sent=self.sent, bytes_recv=self.recv)


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def cfg(**kw):
    base = dict(data_dir=":memory:", host_label="secret-hostname", disk_paths="/", saas_url="http://127.0.0.1:1")
    base.update(kw)
    return Config(**base)


def listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(50)
    return srv, srv.getsockname()[1]


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---- parsing ----
def test_target_parsing():
    assert parse_target("db.internal:5432").port == 5432
    assert [t.label for t in parse_targets("a:1, b:2")] == ["a:1", "b:2"]
    assert parse_services("api=10.0.0.5:8080")[0][0] == "api"
    for bad in ["nohost", "host:", "host:99999", ":80", "host:abc"]:
        with pytest.raises(ValueError):
            parse_target(bad)
    with pytest.raises(ValueError):
        parse_services("missing-equals:80")


# ---- the host itself ----
def test_host_metrics_and_bandwidth_delta():
    ps, clock = FakePsutil(), Clock()
    s = HostSampler(cfg(), ps, clock)
    s.prime()
    clock.t += 1.0
    ps.sent, ps.recv = 6_250_000, 6_250_000  # 12.5 MB in 1 s = 100 Mbps
    got = {r["name"]: r["value"] for r in s.sample_host()}
    assert got == {"cpu_pct": 42.0, "mem_pct": 61.5, "disk_pct": 70.0, "bandwidth_mbps": 100.0}


def test_first_sample_without_prime_has_no_bandwidth_and_idle_link_is_zero():
    ps, clock = FakePsutil(), Clock()
    s = HostSampler(cfg(), ps, clock)
    assert "bandwidth_mbps" not in {r["name"] for r in s.sample_host()}  # nothing to diff against yet
    clock.t += 2
    assert {r["name"]: r["value"] for r in s.sample_host()}["bandwidth_mbps"] == 0.0


def test_counter_reset_never_gives_negative_bandwidth():
    ps, clock = FakePsutil(), Clock()
    ps.sent = 10_000_000
    s = HostSampler(cfg(), ps, clock)
    s.prime()
    ps.sent = 0  # interface reset
    clock.t += 1
    assert {r["name"]: r["value"] for r in s.sample_host()}["bandwidth_mbps"] == 0.0


def test_fullest_disk_wins_and_unreadable_disk_is_skipped():
    ps = FakePsutil()
    ps.disk = {"/": 40.0, "/data": 91.0}
    s = HostSampler(cfg(disk_paths="/,/data,/missing"), ps, Clock())
    assert {r["name"]: r["value"] for r in s.sample_host()}["disk_pct"] == 91.0


# ---- probes ----
def test_tcp_probe_reachable_and_unreachable():
    srv, port = listener()
    try:
        latency, loss = tcp_probe("127.0.0.1", port, attempts=3, timeout=1.0)
        assert latency is not None and latency >= 0 and loss == 0.0
    finally:
        srv.close()
    latency, loss = tcp_probe("127.0.0.1", closed_port(), attempts=3, timeout=0.5)
    assert latency is None and loss == 100.0


def test_paths_report_latency_loss_and_connectivity():
    srv, port = listener()
    try:
        s = HostSampler(cfg(saas_url=f"http://127.0.0.1:{port}", probe_attempts=2), FakePsutil(), Clock())
        up = {r["name"]: r["value"] for r in s.sample_paths()}
        assert up["connectivity_up"] == 1.0 and up["packet_loss_pct"] == 0.0 and up["latency_ms"] >= 0
    finally:
        srv.close()
    down = {r["name"]: r["value"] for r in HostSampler(cfg(saas_url=f"http://127.0.0.1:{closed_port()}", probe_attempts=2, probe_timeout_s=0.3), FakePsutil(), Clock()).sample_paths()}
    assert down["connectivity_up"] == 0.0 and down["packet_loss_pct"] == 100.0
    assert "latency_ms" not in down  # no latency to report when nothing answered


def test_saas_path_is_probed_by_default_and_extra_targets_are_added():
    s = HostSampler(cfg(saas_url="https://saas.example:8443", probe_targets="10.0.0.1:53"), FakePsutil(), Clock())
    assert [t.label for t in s.targets] == ["saas.example:8443", "10.0.0.1:53"]


def test_service_checks_report_up_and_down_per_service():
    srv, port = listener()
    try:
        s = HostSampler(cfg(service_checks=f"api=127.0.0.1:{port},db=127.0.0.1:{closed_port()}", probe_timeout_s=0.3), FakePsutil(), Clock())
        recs = s.sample_services()
        assert {r["host"].split(":")[1]: r["value"] for r in recs} == {"api": 1.0, "db": 0.0}
        assert all(r["name"] == "service_up" for r in recs)
    finally:
        srv.close()


# ---- end to end through the pipeline ----
def test_all_six_metrics_reach_the_outbox_pseudonymized():
    srv, port = listener()
    try:
        ps, clock = FakePsutil(), Clock()
        c = cfg(saas_url=f"http://127.0.0.1:{port}", probe_attempts=1, window_s=5, grace_s=0)
        store = LocalStore(":memory:")
        pipeline = Pipeline(c, store)
        source = HostSource(c, pipeline, HostSampler(c, ps, clock))
        source.sampler.prime()
        clock.t += 1
        ps.sent = ps.recv = 1_000_000
        source._ingest(source.sampler.sample_host())
        source._ingest(source.sampler.sample_slow())
        pipeline.flush(force=True)

        payloads = [e["payload"] for e in store.recent_egress(100)]
        names = {p["metric"]["name"] for p in payloads}
        assert {"cpu_pct", "mem_pct", "disk_pct", "bandwidth_mbps", "latency_ms", "packet_loss_pct"} <= names
        for p in payloads:
            Payload.model_validate(p)
        blob = json.dumps(store.recent_egress(100))
        assert "secret-hostname" not in blob and "127.0.0.1" not in blob  # real names stay local
        assert len({p["source_id"] for p in payloads}) == 2  # the host and the network path are separate sources
    finally:
        srv.close()


def test_host_source_survives_a_failing_sampler_and_keeps_running():
    class Broken(HostSampler):
        def sample_host(self):
            raise RuntimeError("boom")

    c = cfg(host_interval_s=0.01)
    source = HostSource(c, Pipeline(c, LocalStore(":memory:")), Broken(c, FakePsutil(), Clock()))

    async def go():
        task = asyncio.create_task(source.run())
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(go())
    assert source.errors >= 2  # it kept trying instead of dying on the first error


def test_real_psutil_returns_sane_values():
    psutil = pytest.importorskip("psutil")
    s = HostSampler(cfg(disk_paths=""), psutil, __import__("time").time)
    s.prime()
    got = {r["name"]: r["value"] for r in s.sample_host()}
    assert 0 <= got["cpu_pct"] <= 100 and 0 < got["mem_pct"] <= 100 and 0 < got["disk_pct"] <= 100


def test_adaptive_sampling_opt_in_hysteresis():
    c=cfg(adaptive_telemetry=True,host_interval_s=2)
    source=HostSource(c,None,sampler=HostSampler(c,psutil_mod=FakePsutil(),clock=Clock()))
    records=lambda cpu,mem:[{'name':'cpu_pct','value':cpu},{'name':'mem_pct','value':mem}]
    assert source.sampling_interval(records(30,50)) == 2
    assert source.sampling_interval(records(81,50)) == 1
    assert source.adaptive_mode == 'fast'
    assert source.sampling_interval(records(50,50)) == 1
    assert source.sampling_interval(records(50,50)) == 1
    assert source.sampling_interval(records(50,50)) == 2
    assert source.adaptive_mode == 'normal'
    off=cfg(adaptive_telemetry=False,host_interval_s=2)
    disabled=HostSource(off,None,sampler=HostSampler(off,psutil_mod=FakePsutil(),clock=Clock()))
    assert disabled.sampling_interval(records(99,99)) == 2
