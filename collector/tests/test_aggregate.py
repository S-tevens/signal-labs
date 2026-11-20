import json

from collector.aggregate import Aggregator
from collector.config import Config
from collector.outbox import LocalStore
from collector.pipeline import Pipeline

T0 = 1_800_000_000  # a fixed instant, divisible by 5 so windows are easy to reason about


def make(window_s=5, burst=5, **cfg):
    config = Config(data_dir=":memory:", window_s=window_s, grace_s=0, burst_threshold=burst, **cfg)
    store = LocalStore(":memory:")
    return Pipeline(config, store), store


def metric(name, value, ts, host="web-1"):
    return json.dumps({"kind": "metric", "host": host, "name": name, "value": value, "ts": _iso(ts)})


def _iso(epoch):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def failed(i, host="web-1"):
    return f"Nov 20 09:16:{i % 60:02d} {host} sshd[88]: Failed password for root from 203.0.113.{i % 250 + 1}"


def payloads(store):
    return [e["payload"] for e in store.recent_egress(1000)]


# ---- aggregation ----
def test_many_metric_samples_become_one_mean_per_window():
    p, store = make()
    for i, v in enumerate([10, 20, 30, 40, 50]):
        p.process(metric("cpu_pct", v, T0 + i))
    p.flush(force=True)
    out = payloads(store)
    assert len(out) == 1
    assert out[0]["metric"] == {"name": "cpu_pct", "value": 30.0, "unit": "%"}
    assert out[0]["window_s"] == 5


def test_boolean_metric_reports_the_minimum_so_a_failure_is_not_averaged_away():
    p, store = make()
    for i, v in enumerate([1, 1, 0, 1, 1]):
        p.process(metric("service_up", v, T0 + i))
    p.flush(force=True)
    assert payloads(store)[0]["metric"]["value"] == 0.0


def test_separate_windows_and_sources_stay_separate():
    p, store = make()
    p.process(metric("cpu_pct", 10, T0))
    p.process(metric("cpu_pct", 90, T0 + 5))  # next window
    p.process(metric("cpu_pct", 50, T0, host="db-1"))  # other source
    p.flush(force=True)
    assert len(payloads(store)) == 3


def test_window_closes_by_event_time_not_before_grace():
    agg = Aggregator(window_s=5, grace_s=2)
    agg.add_metric("src_a", "cpu_pct", 10, T0)
    assert agg.flush(now=T0 + 6) == []  # window ended at T0+5 but grace runs until T0+7
    assert len(agg.flush(now=T0 + 7)) == 1


def test_late_event_is_sent_alone_not_lost():
    p, store = make()
    p.process(metric("cpu_pct", 10, T0))
    p.flush(force=True)
    p.process(metric("cpu_pct", 99, T0 + 1))  # same window, already sent
    out = payloads(store)
    assert len(out) == 2 and sorted(x["window_s"] for x in out) == [1, 5]
    assert sorted(x["metric"]["value"] for x in out) == [10.0, 99.0]


def test_raw_record_ids_are_kept_for_lineage():
    p, store = make()
    for i in range(3):
        p.process(metric("cpu_pct", 10 + i, T0 + i))
    p.flush(force=True)
    assert len(store.recent_egress(1)[0]["raw_ids"]) == 3


# ---- failed-login burst (the E1 done-when) ----
def test_forty_failed_logins_become_one_burst_event_and_no_per_line_events():
    p, store = make()
    for i in range(40):
        p.process(failed(i))
    p.flush(force=True)
    out = payloads(store)
    assert len(out) == 1
    ev = out[0]["event"]
    assert ev["category"] == "auth_failure_burst" and ev["count"] == 40
    assert ev["severity"] == "critical"  # 40 failures is at least 5x the threshold of 5
    assert ev["summary"] == "repeated failed logins"


def test_a_few_failures_are_a_warning_not_a_burst():
    p, store = make(burst=5)
    for i in range(3):
        p.process(failed(i))
    p.flush(force=True)
    ev = payloads(store)[0]["event"]
    assert ev["category"] == "auth_failure" and ev["severity"] == "warning" and ev["count"] == 3


def test_burst_threshold_boundaries():
    for count, category, severity in [(4, "auth_failure", "warning"), (5, "auth_failure_burst", "high"), (25, "auth_failure_burst", "critical")]:
        p, store = make(burst=5)
        for i in range(count):
            p.process(failed(i))
        p.flush(force=True)
        ev = payloads(store)[0]["event"]
        assert (ev["category"], ev["severity"], ev["count"]) == (category, severity, count)


def test_burst_payload_leaks_no_username_ip_or_message():
    p, store = make()
    for i in range(10):
        p.process(failed(i))
    p.flush(force=True)
    blob = json.dumps(store.recent_egress(100))
    for secret in ["root", "203.0.113", "Failed password", "web-1", "sshd"]:
        assert secret not in blob
    assert "root" in json.dumps(store.recent_raw(5))  # but the operator can still see it locally


def test_other_logs_are_counted_not_forwarded_line_by_line():
    p, store = make()
    for i in range(7):
        p.process(f"Nov 20 09:16:{i:02d} web-1 app[1]: GET /health 200")
    p.flush(force=True)
    out = payloads(store)
    assert len(out) == 1 and out[0]["event"]["category"] == "log_event" and out[0]["event"]["count"] == 7


def test_pipeline_counters_add_up():
    p, store = make()
    for i in range(4):
        p.process(metric("cpu_pct", 10, T0 + i))
    p.process(metric("unknown_metric", 1, T0))
    p.flush(force=True)
    assert p.counters["received"] == 5 and p.counters["dropped"] == 1 and p.counters["payloads"] == 1
