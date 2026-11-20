"""Input mapping, adapters and replay (E16, E17)."""
import asyncio
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

from collector import mapping
from collector.adapters import Adapters
from collector.config import Config
from collector.outbox import LocalStore
from collector.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]


def load_sim(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "simulator" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


samples, replay = load_sim("samples"), load_sim("replay")


def make_pipeline(**kw):
    cfg = Config(data_dir=":memory:", host_telemetry=False, grace_s=0, **kw)
    store = LocalStore(":memory:")
    return Pipeline(cfg, store), store, cfg


def run_sample(name):
    pipe, store, _ = make_pipeline()
    pipe.process_text("\n".join(samples.SAMPLES[name]()))
    pipe.flush(force=True)
    return [e["payload"] for e in store.recent_egress(500)], store, pipe


def metrics_of(payloads):
    return {p["metric"]["name"]: p["metric"]["value"] for p in payloads if "metric" in p}


# ---- five differently shaped streams, all producing valid payloads ----
def test_wide_ndjson_with_epoch_ms_and_unit_conversions():
    payloads, _, _ = run_sample("wide-ndjson")
    m = metrics_of(payloads)
    assert m["cpu_pct"] == pytest.approx(42.0)  # ratio 0.42 -> %
    assert m["mem_pct"] == pytest.approx(62.0)  # 100 - free 38
    assert m["latency_ms"] == pytest.approx(45.0)  # seconds -> ms


def test_csv_header_with_day_first_dates_and_aliases():
    payloads, _, _ = run_sample("csv-header")
    m = metrics_of(payloads)
    assert m["cpu_pct"] == pytest.approx(61.5) and m["bandwidth_mbps"] == pytest.approx(88.0)
    assert m["packet_loss_pct"] == pytest.approx(0.2)
    assert {p["event_ts_utc"][:4] for p in payloads if "metric" in p} == {str(__import__("datetime").datetime.now().year)}


def test_key_value_with_other_field_names():
    payloads, _, _ = run_sample("key-value-aliases")
    m = metrics_of(payloads)
    assert m["disk_pct"] == pytest.approx(71.2) and m["service_up"] == 1


def test_syslog_failed_logins_become_one_burst_event_and_no_ips_leave():
    payloads, _, _ = run_sample("syslog-logins")
    events = [p["event"] for p in payloads if "event" in p]
    assert events and events[0]["category"].startswith("auth_failure") and events[0]["count"] == 12
    assert "203.0.113" not in json.dumps(payloads)


def test_mixed_text_never_leaks_secrets_or_unknown_fields():
    payloads, _, _ = run_sample("mixed-text")
    text = json.dumps(payloads)
    for secret in ("alice@corp.com", "abc123def456", "sk_live_abcdef123456", "Hunter2"):
        assert secret not in text


def test_unknown_fields_are_dropped_before_the_pipeline():
    records = mapping.get().normalize({"hostname": "h", "cpu_ratio": 0.5, "rack": "r7", "api_token": "tok_live_x"})
    assert records == [{"ts": None, "tz": None, "host": "h", "kind": "metric", "name": "cpu_pct", "value": 50.0}]
    payloads, _, _ = run_sample("wide-ndjson")
    assert "tok_live_should_never_travel" not in json.dumps(payloads) and "payments-team" not in json.dumps(payloads)


# ---- mapping behaviour ----
def test_time_forms():
    m = mapping.get()
    assert m.timestamp(1_800_000_000) == m.timestamp(1_800_000_000_000) == m.timestamp("1800000000000000") == "2027-01-15T08:00:00Z"
    assert m.timestamp("15/01/2027 08:00:00") == "2027-01-15T08:00:00Z"
    assert m.timestamp("2027-01-15T13:30:00+05:30") == "2027-01-15T08:00:00Z"
    assert m.timestamp("garbage") is None and m.timestamp(None) is None


def test_bad_mapping_files_fail_loudly(tmp_path):
    good = (ROOT / "collector" / "mapping.yaml").read_text(encoding="utf-8")
    for bad in (good + "\nsurprise: 1\n", good.replace("cpu: cpu_pct", "cpu: not_a_metric"), good.replace("host_fields: [", "host_fields: []#[")):
        f = tmp_path / "m.yaml"
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(mapping.MappingError):
            mapping.load(f)


def test_a_new_format_needs_only_a_mapping_file(tmp_path, monkeypatch):
    f = tmp_path / "m.yaml"
    f.write_text((ROOT / "collector" / "mapping.yaml").read_text(encoding="utf-8").replace("metrics:\n", "metrics:\n  prozessor: cpu_pct\n"), encoding="utf-8")
    monkeypatch.setenv("MAPPING_FILE", str(f))
    try:
        pipe, store, _ = make_pipeline()
        pipe.process_text(json.dumps({"hostname": "h", "prozessor": 55}))
        pipe.flush(force=True)
        assert metrics_of([e["payload"] for e in store.recent_egress(10)]) == {"cpu_pct": 55.0}
    finally:
        monkeypatch.delenv("MAPPING_FILE")
        mapping.get()


def test_the_existing_formats_still_parse():
    pipe, store, _ = make_pipeline()
    pipe.process_text('{"kind": "metric", "ts": "2026-11-20T10:00:01Z", "host": "a", "name": "cpu_pct", "value": 40}\nts=2026-11-20T10:00:02Z host=a metric=mem_pct value=50')
    pipe.flush(force=True)
    assert set(metrics_of([e["payload"] for e in store.recent_egress(10)])) == {"cpu_pct", "mem_pct"}


# ---- adapters ----
def free_port(kind):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_udp_tcp_and_file_adapters_feed_the_pipeline(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("old line that must not be read\n", encoding="utf-8")
    udp, tcp = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
    pipe, store, cfg = make_pipeline(udp_syslog_port=udp, tcp_lines_port=tcp, follow_files=str(log))

    async def go():
        a = Adapters(cfg, pipe)
        await a.start()
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, remote_addr=("127.0.0.1", udp))
        transport.sendto(b"ts=2026-11-20T10:00:01Z host=u metric=cpu_pct value=11\n")
        transport.close()
        _, w = await asyncio.open_connection("127.0.0.1", tcp)
        w.write(b"ts=2026-11-20T10:00:02Z host=t metric=cpu_pct value=22\n")
        await w.drain()
        w.close()
        await asyncio.sleep(0.7)
        with open(log, "a", encoding="utf-8") as f:
            f.write("ts=2026-11-20T10:00:03Z host=f metric=cpu_pct value=33\n")
        await asyncio.sleep(1.2)
        log.write_text("ts=2026-11-20T10:00:04Z host=r metric=cpu_pct value=44\n", encoding="utf-8")  # rotated: smaller file
        await asyncio.sleep(1.2)
        await a.stop()

    asyncio.run(go())
    pipe.flush(force=True)
    values = sorted(p["metric"]["value"] for p in (e["payload"] for e in store.recent_egress(50)) if "metric" in p)
    assert values == [11.0, 22.0, 33.0, 44.0]  # the old line was never read; the rotated file was read from its start
    assert pipe.counters["adapter:udp"] == 1 and pipe.counters["adapter:tcp"] == 1


def test_adapters_are_off_by_default_and_bind_to_this_machine():
    cfg = Config(data_dir=":memory:")
    assert cfg.udp_syslog_port == 0 and cfg.tcp_lines_port == 0 and cfg.follow_files == "" and cfg.adapter_bind == "127.0.0.1"


# ---- replay and timelines ----
TIMELINE = json.loads((ROOT / "simulator" / "timelines" / "demo.json").read_text(encoding="utf-8"))


def test_a_timeline_builds_the_same_recording_every_time():
    assert replay.dump(replay.build(TIMELINE)) == replay.dump(replay.build(TIMELINE))
    assert replay.dump(replay.build({**TIMELINE, "seed": 8})) != replay.dump(replay.build(TIMELINE))


def test_the_demo_timeline_contains_every_scripted_injection_at_its_time():
    rows = replay.build(TIMELINE)
    assert rows[-1]["t"] <= 300 and rows[0]["t"] == 0
    spike = [r for r in rows if "line" in r and "web-1" in r["line"] and "cpu_pct" in r["line"] and "97" in r["line"] and 90 <= r["t"] < 120]
    assert spike
    assert not [r for r in rows if "line" in r and "97" in r["line"] and "web-1" in r["line"] and "cpu_pct" in r["line"] and r["t"] < 90]
    assert sum(1 for r in rows if "line" in r and "Failed password" in r["line"] and r["t"] == 190) == 30
    assert [(r["t"], r["state"]) for r in rows if r.get("action")] == [(230.0, "down"), (255.0, "up")]


def test_a_recording_round_trips_and_a_raw_log_is_rebased(tmp_path):
    rows = replay.build({**TIMELINE, "length_s": 10})
    f = tmp_path / "r.jsonl"
    f.write_text(replay.dump(rows), encoding="utf-8")
    assert replay.load(f) == rows
    raw = tmp_path / "x.log"
    raw.write_text("2020-01-01T10:00:00Z a metric=cpu_pct value=1\n2020-01-01T10:00:07Z b metric=cpu_pct value=2\nno stamp here\n", encoding="utf-8")
    got = replay.load(raw)
    assert [r["t"] for r in got] == [0.0, 7.0, 7.0] and all("2020" not in r["line"] for r in got) and "@T@" in got[0]["line"]


def test_play_sends_live_timestamps_and_controls_the_link(monkeypatch):
    sent, calls = [], []
    monkeypatch.setattr(replay, "_post", lambda path, data=b"", headers=None: (sent.append(data.decode()) if path == "/ingest" else calls.append(path)) or True)
    rows = [{"t": 0.0, "line": "ts=@T@ host=a metric=cpu_pct value=1"}, {"t": 0.2, "action": "link", "state": "down"}, {"t": 0.4, "line": "ts=@T@ host=a metric=cpu_pct value=2"}]
    out = replay.play(rows, speed=2.0, log=lambda *_: None)
    assert out["lines_sent"] == 2 and calls == ["/local/saas-link/down"]
    year = str(__import__("datetime").datetime.now().year)
    assert all(f"ts={year}" in s for s in sent)
