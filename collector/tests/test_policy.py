import copy
import json
from pathlib import Path

import pytest
import yaml

from collector.config import Config
from collector.outbox import LocalStore
from collector.pipeline import Pipeline
from collector.policy import Policy, PolicyError

POLICY_FILE = Path(__file__).resolve().parents[1] / "policy.yaml"
T0 = 1_800_000_000


def data():
    return copy.deepcopy(yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8")))


def pipeline_with(policy_data):
    cfg = Config(data_dir=":memory:", window_s=5, grace_s=0)
    store = LocalStore(":memory:")
    return Pipeline(cfg, store, Policy(policy_data)), store


def line(name, value=50, host="web-1"):
    from datetime import datetime, timezone

    ts = datetime.fromtimestamp(T0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps({"kind": "metric", "host": host, "name": name, "value": value, "ts": ts})


def test_shipped_policy_loads_and_describes_every_field():
    d = Policy.load(POLICY_FILE).describe()
    assert {"payload_id", "source_id", "metric", "event"} <= set(d["egress_fields"])
    assert d["egress_fields"]["source_id"]["classification"] == "PSEUDONYMIZED"
    assert d["local_only"]["raw_message"]


def test_shipped_policy_matches_the_payload_schema_fields():
    """The policy must list exactly the fields the schema can carry, or valid payloads would be blocked."""
    from collector.schema import Payload

    assert set(Policy.load(POLICY_FILE).fields) == set(Payload.model_fields)


def test_removing_a_metric_from_policy_stops_it_leaving():
    d = data()
    d["metrics"].remove("disk_pct")
    p, store = pipeline_with(d)
    p.process(line("disk_pct"))
    p.process(line("cpu_pct"))
    p.flush(force=True)
    names = [e["payload"]["metric"]["name"] for e in store.recent_egress()]
    assert names == ["cpu_pct"]
    assert p.counters["blocked_by_policy"] == 1


def test_removing_an_event_category_blocks_it():
    d = data()
    d["event_categories"].remove("log_event")
    p, store = pipeline_with(d)
    p.process("Nov 20 09:16:01 web-1 app[1]: hello")
    p.flush(force=True)
    assert store.depth() == 0 and p.counters["blocked_by_policy"] == 1


def test_removing_a_required_field_fails_closed():
    d = data()
    del d["fields"]["source_tz"]
    p, store = pipeline_with(d)
    p.process(line("cpu_pct"))
    p.flush(force=True)
    assert store.depth() == 0 and p.counters["blocked_by_policy"] == 1


def test_removing_the_metric_field_blocks_every_metric():
    d = data()
    del d["fields"]["metric"]
    p, store = pipeline_with(d)
    p.process(line("cpu_pct"))
    p.flush(force=True)
    assert store.depth() == 0


def test_apply_strips_fields_the_policy_does_not_list():
    policy = Policy(data())
    ok = {k: "x" for k in policy.fields}
    ok["metric"] = {"name": "cpu_pct", "value": 1, "unit": "%"}
    ok.pop("event", None)
    decision = policy.apply({**ok, "raw_message": "password=hunter2"})
    assert not decision.blocked and "raw_message" not in decision.payload
    assert any("raw_message" in v for v in decision.violations)


def test_local_only_field_cannot_also_be_an_egress_field():
    d = data()
    d["fields"]["raw_message"] = {"classification": "ALLOWED_METADATA"}
    with pytest.raises(PolicyError):
        Policy(d)


def test_a_local_only_marking_cannot_be_used_as_an_egress_field():
    d = data()
    d["fields"]["payload_id"]["classification"] = "LOCAL_ONLY"
    with pytest.raises(PolicyError):
        Policy(d)


def test_unknown_classification_unknown_rule_and_stray_keys_are_rejected():
    d = data()
    d["fields"]["payload_id"]["classification"] = "TOP_SECRET"
    with pytest.raises(PolicyError):
        Policy(d)
    d = data()
    d["redaction_rules"].append("not_a_rule")
    with pytest.raises(PolicyError):
        Policy(d)
    d = data()
    d["fields"]["payload_id"]["never sent"] = None  # what an unquoted comma in YAML produces
    with pytest.raises(PolicyError):
        Policy(d)
