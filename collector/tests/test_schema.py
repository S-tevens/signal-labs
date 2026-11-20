import pytest
from pydantic import ValidationError

from collector.schema import Payload

BASE = {
    "payload_id": "b3f1c2d4-0000-4000-8000-123456789abc",
    "tenant_ref": "t-acme",
    "collector_id": "col-blr-01",
    "source_id": "src_9fa2c1d3e4f5",
    "region": "in",
    "event_ts_utc": "2026-11-20T09:15:00Z",
    "source_tz": "Asia/Kolkata",
    "window_s": 5,
    "health_state": "Good",
    "collector_version": "0.1.0",
}
METRIC = {"name": "cpu_pct", "value": 91.2, "unit": "%"}
EVENT = {"category": "auth_failure_burst", "severity": "high", "count": 42, "summary": "repeated failed logins"}


def test_valid_metric_and_event():
    assert Payload(**BASE, metric=METRIC).metric.value == 91.2
    assert Payload(**BASE, event=EVENT).event.count == 42


def test_extra_top_level_field_rejected():
    with pytest.raises(ValidationError):
        Payload(**BASE, metric=METRIC, raw_message="password=hunter2")


def test_extra_nested_field_rejected():
    with pytest.raises(ValidationError):
        Payload(**BASE, event={**EVENT, "username": "alice"})


def test_exactly_one_body():
    with pytest.raises(ValidationError):
        Payload(**BASE)
    with pytest.raises(ValidationError):
        Payload(**BASE, metric=METRIC, event=EVENT)


def test_unknown_metric_and_wrong_unit_rejected():
    with pytest.raises(ValidationError):
        Payload(**BASE, metric={"name": "secret_metric", "value": 1, "unit": "%"})
    with pytest.raises(ValidationError):
        Payload(**BASE, metric={"name": "cpu_pct", "value": 1, "unit": "ms"})


def test_non_utc_timestamp_rejected():
    with pytest.raises(ValidationError):
        Payload(**{**BASE, "event_ts_utc": "2026-11-20T09:15:00+05:30"}, metric=METRIC)
    with pytest.raises(ValidationError):
        Payload(**{**BASE, "event_ts_utc": "2026-11-20T09:15:00"}, metric=METRIC)


def test_summary_cannot_carry_arbitrary_text():
    with pytest.raises(ValidationError):
        Payload(**BASE, event={**EVENT, "summary": "password=hunter2 user=alice@corp.com"})
