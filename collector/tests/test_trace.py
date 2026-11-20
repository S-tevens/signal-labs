"""The payload trace's pure parts (E27): masking, the leak check and the incident summary."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("trace_tool", Path(__file__).resolve().parents[2] / "simulator" / "trace.py")
trace = importlib.util.module_from_spec(_spec)
sys.modules["trace_tool"] = trace
_spec.loader.exec_module(trace)

TEXT = "login password=Hunter2! from 10.2.4.7 ok"
SPANS = [{"start": 6, "end": 23, "rule": "password"}, {"start": 29, "end": 37, "rule": "ipv4"}]


def test_masking_hides_every_sensitive_span_and_keeps_the_rest():
    out = trace.mask(TEXT, SPANS)
    assert "Hunter2" not in out and "10.2.4.7" not in out and out.startswith("login [password:17 chars]") and out.endswith(" ok")
    assert trace.mask(TEXT, SPANS, reveal=True) == TEXT


def test_overlapping_spans_are_merged_not_double_masked():
    out = trace.mask("abcdefghij", [{"start": 1, "end": 5, "rule": "a"}, {"start": 3, "end": 8, "rule": "b"}])
    assert out == "a[a+b:7 chars]ij"


def test_the_leak_check_finds_a_value_in_the_payload_and_ignores_clean_ones():
    raw = [{"text": TEXT, "spans": SPANS}]
    assert trace.leaked({"summary": "x"}, raw) == []
    assert trace.leaked({"summary": "password was Hunter2! here"}, raw) == ["password"]


def test_received_hop_reports_missing_and_differences():
    payload = {"payload_id": "p", "event_ts_utc": "2026-11-20T10:00:05Z", "metric": {"name": "cpu_pct", "value": 1.0, "unit": "%"}}
    assert trace.hop_received(payload, None)[0] is False
    ok, _ = trace.hop_received(payload, {**payload, "event_ts_utc": "2026-11-20T10:00:05.000000Z"})
    assert ok
    assert trace.hop_received(payload, {**payload, "metric": {"name": "cpu_pct", "value": 2.0, "unit": "%"}})[0] is False


def test_incident_summary_keeps_only_this_payloads_signals():
    inc = {"id": "i1", "properties": {"severity": "critical", "source_id": "s", "signals": [
        {"payload_id": "p1", "signal": "failed_login", "value": 30, "why": "w", "method": "local event summary"},
        {"payload_id": "p2", "signal": "cpu_pct", "value": 99}],
        "recommendation": {"action": "Review", "confidence": "low", "nested": {"x": 1}}}}
    s = trace.summarize_incident(inc, "p1")
    assert s["signals_in_incident"] == 2 and [x["signal"] for x in s["signals_from_this_payload"]] == ["failed_login"]
    assert s["recommendation"] == {"action": "Review", "confidence": "low"}
