"""Guards the collector <-> SaaS seam: what the collector sends must validate under the SaaS models."""
import json
from datetime import datetime, timezone

from collector.config import Config
from collector.outbox import LocalStore
from collector.pipeline import Pipeline
from saas.schema import Heartbeat, Payload


def test_every_collector_payload_validates_under_saas_schema():
    cfg = Config(data_dir=":memory:")
    store = LocalStore(":memory:")
    pipeline = Pipeline(cfg, store)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        json.dumps({"kind": "metric", "ts": now, "tz": "Asia/Kolkata", "host": "web-1", "name": "cpu_pct", "value": 91}),
        f"ts={now} host=router-1 metric=latency_ms value=120.5",
        "Nov 20 09:15:01 web-1 sshd[88]: Failed password for root from 10.2.4.7",
        "plain text line",
    ]
    for line in lines:
        assert pipeline.process(line)["status"] == "queued"
    sent = store.pending(50)
    assert len(sent) == len(lines)
    for p in sent:
        Payload.model_validate(p)  # strict, extra=forbid: raises if the seam drifts


def test_heartbeat_body_matches_saas_model():
    body = {"collector_id": "col-blr-01", "collector_version": "0.1.0", "config_hash": "dev", "resource_usage": {}}
    Heartbeat.model_validate(body)
