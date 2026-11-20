"""The collector's own health verdict agrees with the platform's (E23)."""
from pathlib import Path

import pytest
import yaml

from collector import health
from collector.config import Config
from collector.outbox import LocalStore
from collector.pipeline import Pipeline
from saas.aiops import canonical
from saas.health import metric_state as platform_state

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = yaml.safe_load((ROOT / "saas" / "config" / "thresholds.yaml").read_text(encoding="utf-8"))


def test_the_collector_thresholds_equal_the_platforms():
    for name, rule in health.rules().items():
        theirs = PLATFORM["metrics"][canonical(name)]
        assert {k: theirs[k] for k in rule} == rule, name


@pytest.mark.parametrize("name", list(health.rules()))
def test_the_verdict_matches_the_platform_at_and_around_every_threshold(name):
    r = health.rules()[name]
    for v in [r["good"], r["fair"], r["poor"]] + [x + d for x in (r["good"], r["fair"], r["poor"]) for d in (-0.01, 0.01)] + [0, 100, 1000]:
        assert health.metric_state(name, v) == platform_state({"name": name, "value": v}, PLATFORM), (name, v)


def test_a_metric_without_a_threshold_is_excellent_like_the_platform():
    assert health.metric_state("bandwidth_mbps", 900) == "Excellent" == platform_state({"name": "bandwidth_mbps", "value": 900}, PLATFORM)


def queued(lines):
    pipe = Pipeline(Config(data_dir=":memory:", host_telemetry=False, grace_s=0), LocalStore(":memory:"))
    pipe.process_text("\n".join(lines))
    pipe.flush(force=True)
    return [e["payload"] for e in pipe.store.recent_egress(50)]


def test_a_cpu_spike_changes_the_health_state_the_collector_sends():
    calm = queued(["ts=2026-11-20T10:00:01Z host=a metric=cpu_pct value=35"])
    spike = queued(["ts=2026-11-20T10:00:01Z host=a metric=cpu_pct value=97"])
    assert calm[0]["health_state"] == "Excellent" and spike[0]["health_state"] == "Poor"


def test_a_failed_login_burst_is_reported_poor():
    lines = [f'ts=2026-11-20T10:00:01Z host=a msg="Failed password for root from 203.0.113.{i} port 22"' for i in range(30)]
    events = [p for p in queued(lines) if "event" in p]
    assert events and events[0]["event"]["severity"] == "critical" and events[0]["health_state"] == "Poor"
