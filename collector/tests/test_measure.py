"""The measurement harness's arithmetic and attribution (the parts that decide PASS or FAIL)."""
import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("measure", Path(__file__).resolve().parents[2] / "simulator" / "measure.py")
measure = importlib.util.module_from_spec(_spec)
sys.modules["measure"] = measure
_spec.loader.exec_module(measure)

T = 1_800_000_000.0  # a window boundary (divisible by 5)


def iso(epoch):
    return measure.iso_ms(epoch)


# ---- percentiles ----
def test_percentile_is_nearest_rank_like_the_platform():
    assert measure.percentile([], 0.95) is None
    assert measure.percentile([7], 0.95) == 7
    values = list(range(1, 101))  # 1..100
    assert measure.percentile(values, 0.95) == 95 and measure.percentile(values, 0.50) == 50 and measure.percentile(values, 0.99) == 99
    assert measure.percentile([3, 1, 2], 0.5) == 2  # sorts first


def test_stats_of_nothing_is_all_none():
    s = measure.stats([])
    assert s["n"] == 0 and s["p95"] is None


def test_timestamps_round_trip():
    assert measure.parse_ts(iso(T + 0.123)) == pytest.approx(T + 0.123, abs=1e-3)
    assert measure.parse_ts("2026-11-20T15:00:00Z") == measure.parse_ts("2026-11-20T15:00:00.000000+00:00")


def test_window_start():
    assert measure.window_start(T + 4.9, 5) == T
    assert measure.window_start(T + 5.0, 5) == T + 5
    assert measure.window_start(T + 1.5, 2) == T


# ---- attribution through the collector's own lineage ----
def test_only_payloads_built_from_our_raw_records_are_attributed():
    raw = [{"id": 1, "text": '{"host":"measure-lat-ab12","name":"cpu_pct"}'}, {"id": 2, "text": '{"host":"other","name":"cpu_pct"}'},
           {"id": 3, "text": "measure-lat-ab12 again"}]
    egress = [
        {"payload_id": "mine-1", "raw_ids": [1, 3], "payload": {"source_id": "src_x"}},
        {"payload_id": "theirs", "raw_ids": [2], "payload": {}},
        {"payload_id": "mine-2", "raw_ids": [3], "payload": {}},
        {"payload_id": "none", "raw_ids": [], "payload": {}},
    ]
    assert set(measure.attribute(egress, raw, "measure-lat-ab12")) == {"mine-1", "mine-2"}


# ---- latency verdict ----
def payload(event_ts, window_s=5):
    return {"event_ts_utc": iso(event_ts), "window_s": window_s}


def test_latency_reports_both_definitions_and_the_strict_one_decides():
    # the newest record is 4.5 s into the window and the dashboard path sees it 6 s after the window started
    payloads = {"a": payload(T + 4.5)}
    seen = {"a": T + 6.0}
    out = measure.latency_summary(payloads, seen, seen)
    assert out["dash_from_newest"]["p95"] == pytest.approx(1.5, abs=1e-2)
    assert out["dash_from_window"]["p95"] == pytest.approx(6.0, abs=1e-2)
    assert out["verdict"] == "PASS"


def test_a_slow_window_start_fails_even_when_the_newest_record_looks_fine():
    payloads = {"a": payload(T + 4.9)}
    seen = {"a": T + 11.0}  # 6.1 s after the newest record, but 11 s after the window began
    out = measure.latency_summary(payloads, seen, seen)
    assert out["dash_from_newest"]["p95"] < 10 < out["dash_from_window"]["p95"]
    assert out["verdict"] == "FAIL"


def test_a_payload_that_never_reaches_the_dashboard_path_fails_the_run():
    payloads = {"a": payload(T + 1), "b": payload(T + 2)}
    out = measure.latency_summary(payloads, {"a": T + 3, "b": T + 3}, {"a": T + 3})
    assert out["never_seen_on_dashboard_path"] == 1 and out["verdict"] == "FAIL"


def test_no_payloads_is_a_failure_not_a_pass():
    assert measure.latency_summary({}, {}, {})["verdict"] == "FAIL"


# ---- alert ----
def test_alert_within_target_passes_and_late_or_missing_fails():
    incident = {"created_at_epoch": T + 11, "alert_count": 3, "signals": [{"signal": "cpu", "method": "x", "value": 99, "event_ts_utc": iso(T + 9), "alert_delay_s": 2.1}]}
    ok = measure.alert_summary(T, incident, T + 11.4, T + 12.0)
    assert ok["verdict"] == "PASS" and ok["from_spike_to_dashboard_path_s"] == 12.0 and ok["from_spike_to_incident_created_s"] == 11.0
    assert measure.alert_summary(T, incident, T + 15.5, T + 16.0)["verdict"] == "FAIL"  # just over 15 s
    assert measure.alert_summary(T, incident, T + 11, None)["verdict"] == "FAIL"  # never reached the dashboard path
    assert measure.alert_summary(T, None, None, None)["verdict"] == "FAIL"  # no alert at all


# ---- offline ----
def test_offline_is_measured_from_the_last_heartbeat_and_the_strict_reading_decides():
    states = {"Fair": T + 31, "Poor": T + 60.5}
    out = measure.offline_summary(t_kill=T, last_seen=T - 3, first_state_at=states, dash_poor=T + 61.2)
    assert out["from_outage_start_to_Poor_s"] == 60.5
    assert out["from_last_heartbeat_to_Poor_s"] == 63.5  # 60.5 s after the kill, but 63.5 s after the last heartbeat
    assert out["verdict"] == "FAIL"  # the strict reading (from the last heartbeat) misses the 60 s target
    quick = measure.offline_summary(T, T - 3, {"Poor": T + 40}, T + 40.5)
    assert quick["from_last_heartbeat_to_Poor_s"] == 43.0 and quick["verdict"] == "PASS"


def test_offline_that_never_turns_poor_fails():
    out = measure.offline_summary(T, T - 2, {}, None)
    assert out["verdict"] == "FAIL" and out["from_outage_start_to_Poor_s"] is None


# ---- delivery ----
def test_delivery_passes_only_with_nothing_missing_and_nothing_duplicated():
    ids = {"a", "b", "c"}
    ok = measure.delivery_summary(ids, ["a", "b", "c", "x"], 2, {})
    assert ok["verdict"] == "PASS" and ok["duplicate_attempts_rejected_by_platform"] == 2  # rejected retries are fine
    lost = measure.delivery_summary(ids, ["a", "b"], 0, {})
    assert lost["verdict"] == "FAIL" and lost["missing_at_platform"] == 1 and lost["missing_examples"] == ["c"]
    dup = measure.delivery_summary(ids, ["a", "b", "c", "c"], 0, {})
    assert dup["verdict"] == "FAIL" and dup["duplicate_rows_at_platform"] == 1


# ---- the report ----
def test_markdown_report_lists_each_target_with_its_verdict():
    results = {
        "latency": measure.latency_summary({"a": payload(T + 1)}, {"a": T + 3}, {"a": T + 3}),
        "alert": measure.alert_summary(T, None, None, None),
        "offline": measure.offline_summary(T, T - 1, {"Poor": T + 20}, T + 21),
        "delivery": measure.delivery_summary({"a"}, ["a"], 0, {"replay_seconds_after_reconnect": 3.2}),
    }
    md = measure.render_markdown({"started_utc": "2026-11-20T10:00:00Z", "settings": {"x": 1}, "results": results})
    assert "**PASS**" in md and "**FAIL**" in md
    for text in ("Collection to dashboard", "Spike to alert", "Collector offline to Poor", "Zero loss", "Settings used"):
        assert text in md
