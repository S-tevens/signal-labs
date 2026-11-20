"""More input shapes (E26): nested JSON, lists of metrics, Prometheus text, InfluxDB line protocol and RFC5424 syslog."""
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

from collector import mapping
from collector.config import Config
from collector.outbox import LocalStore
from collector.parsers import parse_records
from collector.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("samples_more", ROOT / "simulator" / "samples.py")
samples = importlib.util.module_from_spec(_spec)
sys.modules["samples_more"] = samples
_spec.loader.exec_module(samples)


def metrics(records):
    return {(r["name"], round(r["value"], 3)) for r in records if r["kind"] == "metric"}


def run(lines):
    pipe = Pipeline(Config(data_dir=":memory:", host_telemetry=False, grace_s=0), LocalStore(":memory:"))
    pipe.process_text("\n".join(lines))
    pipe.flush(force=True)
    return [e["payload"] for e in pipe.store.recent_egress(200)], pipe


def got(payloads):
    return {(p["metric"]["name"], round(p["metric"]["value"], 1)) for p in payloads if "metric" in p}


# ---- nested JSON ----
def test_elastic_ecs_nesting_becomes_dotted_keys_with_the_host_and_time_found():
    recs = parse_records(samples.ecs_nested(1795214000)[0])
    assert metrics(recs) == {("cpu_pct", 62.0), ("mem_pct", 41.0)}
    assert recs[0]["host"] == "edge-1" and recs[0]["ts"] is None or recs[0]["ts"].startswith("20")


def test_a_list_of_name_value_objects_becomes_one_record_each_and_converts_units():
    recs = parse_records(samples.otel_list(1795214000)[0])
    assert metrics(recs) == {("cpu_pct", 55.0), ("latency_ms", 120.0), ("packet_loss_pct", 1.0)}
    assert {r["host"] for r in recs} == {"edge-1"} and all(r["ts"] == "2026-11-20T22:33:20Z" for r in recs)


def test_a_mapped_name_one_level_down_is_found_by_its_leaf():
    assert metrics(parse_records(json.dumps({"host": "h", "data": {"cpu_pct": 50}}))) == {("cpu_pct", 50.0)}


def test_hostile_nesting_and_huge_lists_do_not_break_the_parser():
    deep = {"host": "h"}
    node = deep
    for _ in range(60):
        node["x"] = {}
        node = node["x"]
    node["cpu_pct"] = 99
    assert parse_records(json.dumps(deep))  # parsed without recursion errors
    big = {"host": "h", "metrics": [{"name": "cpu_pct", "value": i} for i in range(5000)]}
    assert len(parse_records(json.dumps(big))) <= 2001


# ---- Prometheus ----
def test_prometheus_lines_give_host_from_the_instance_label_and_a_millisecond_time():
    recs = parse_records('cpu_pct{instance="web-1:9100",job="node"} 73.5 1795214000000')
    assert recs[0]["host"] == "web-1" and metrics(recs) == {("cpu_pct", 73.5)} and recs[0]["ts"] == "2026-11-20T22:33:20Z"
    assert metrics(parse_records('latency_s{instance="web-1:9100"} 0.2')) == {("latency_ms", 200.0)}


def test_prometheus_comments_are_not_mistaken_for_metrics():
    assert all(r["kind"] == "log" for r in parse_records("# HELP cpu_pct CPU use")) and all(r["kind"] == "log" for r in parse_records("# TYPE cpu_pct gauge"))


# ---- InfluxDB ----
def test_influx_line_protocol_reads_tags_fields_and_nanoseconds():
    recs = parse_records("cpu,host=srv-3,cpu=cpu-total usage_user=41.5,usage_system=2i 1795214000000000000")
    assert metrics(recs) == {("cpu_pct", 41.5)} and recs[0]["host"] == "srv-3" and recs[0]["ts"] == "2026-11-20T22:33:20Z"
    assert metrics(parse_records("mem,host=h used_percent=58.2 1795214000000000000")) == {("mem_pct", 58.2)}


def test_key_value_lines_are_still_key_value_not_influx():
    recs = parse_records("ts=2026-11-21T10:00:01Z host=a metric=cpu_pct value=40")
    assert recs[0]["format"] == "kv" and metrics(recs) == {("cpu_pct", 40.0)}


# ---- RFC5424 ----
def test_rfc5424_syslog_has_a_trusted_time_and_a_host():
    r = parse_records("<38>1 2026-11-21T10:00:01.003Z edge-1 sshd 411 ID47 - Failed password for root")[0]
    assert r["kind"] == "log" and r["host"] == "edge-1" and r["ts"].startswith("2026-11-21T10:00:01")
    assert parse_records("Nov 21 09:15:01 web-1 app[311]: ok")[0]["host"] == "web-1"  # RFC3164 still works


# ---- all new samples through the whole pipeline ----
@pytest.mark.parametrize("name,expect", [
    ("ecs-nested", {("cpu_pct", 62.0), ("mem_pct", 41.0)}),
    ("otel-list", {("cpu_pct", 55.0), ("latency_ms", 120.0), ("packet_loss_pct", 1.0)}),
    ("prometheus", {("cpu_pct", 73.5), ("latency_ms", 200.0)}),
    ("influx", {("cpu_pct", 41.5), ("mem_pct", 58.2)}),
])
def test_each_new_stream_shape_produces_valid_payloads(name, expect):
    payloads, _ = run(samples.SAMPLES[name](time.time()))
    assert expect <= got(payloads), got(payloads)


def test_rfc5424_failed_logins_become_one_burst_event():
    payloads, _ = run(samples.syslog_5424(time.time()))
    events = [p["event"] for p in payloads if "event" in p]
    assert events and events[0]["count"] == 12 and "203.0.113" not in json.dumps(payloads)


def test_nothing_sensitive_leaves_from_any_new_shape():
    lines = ['{"host":{"name":"h"},"system":{"cpu":{"total":{"pct":0.5}}},"user":{"email":"alice@corp.com"},"auth":{"token":"tok_live_abcdef123456"}}',
             'cpu_pct{instance="h:9100",secret="Hunter2!"} 50']
    payloads, _ = run(lines)
    blob = json.dumps(payloads)
    assert "alice@corp.com" not in blob and "tok_live" not in blob and "Hunter2" not in blob


def test_the_stream_checker_accepts_the_new_shapes():
    spec = importlib.util.spec_from_file_location("stream_check2", ROOT / "simulator" / "stream_check.py")
    sc = importlib.util.module_from_spec(spec)
    sys.modules["stream_check2"] = sc
    spec.loader.exec_module(sc)
    for name in ("ecs-nested", "otel-list", "prometheus", "influx"):
        res = sc.analyse(samples.SAMPLES[name](time.time()))
        assert res["verdict"] == "READY", (name, res["numeric_fields_ignored"], res["unknown_metric_names"])
