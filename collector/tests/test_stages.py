"""Pipeline stage counts (E24): they add up, and the page shows them."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from collector.config import Config
from collector.main import create_app
from collector.tests.test_egress_ui import SECRET_LINE

UI = Path(__file__).resolve().parents[1] / "ui"


def make():
    return create_app(Config(data_dir=":memory:", host_telemetry=False, saas_url="http://127.0.0.1:1", grace_s=0, max_line_chars=300), run_sender=False)


def feed(client):
    lines = [
        SECRET_LINE,                                                    # redacted by several rules, becomes a log window
        "ts=2026-11-20T10:00:01Z host=a metric=cpu_pct value=40",        # aggregated metric
        '{"kind": "metric", "ts": "2026-11-20T10:00:01Z", "host": "a", "name": "nonsense_metric", "value": 1}',  # dropped
        "ts=2026-11-20T10:00:02Z host=a metric=mem_pct value=notanumber",  # dropped
        "x" * 400,                                                      # oversize
        'ts=2026-11-20T10:00:03Z host=a msg="Failed password for root from 203.0.113.9 port 22"',
    ]
    client.post("/ingest", content="\n".join(lines))


def test_every_stage_is_counted_and_the_totals_add_up():
    app = make()
    client = TestClient(app, base_url="http://localhost")
    feed(client)
    app.state.pipeline.flush(force=True)
    s = client.get("/local/stages").json()
    assert s["received"] == 6
    assert s["dropped"] == {"oversize_line": 1, "unmapped_or_invalid_record": 2}
    assert s["aggregated_into_windows"] == 3 and s["queued"] >= 2
    assert s["redacted_records_by_rule"]  # the secret line matched at least one rule
    assert all(c["ok"] for c in s["checks"]), s["checks"]
    assert sum(s["outbox_now"].values()) == s["queued"]


def test_a_collector_event_keeps_the_second_identity_balanced():
    app = make()
    app.state.pipeline.emit_collector_event("service_state", "warning", 3, "buffer overflow dropped payloads")
    s = app.state.pipeline.stages()
    assert s["collector_events"] == 1 and s["queued"] == 1 and all(c["ok"] for c in s["checks"])


def test_a_policy_block_is_counted_and_still_balances(monkeypatch):
    app = make()
    pipe = app.state.pipeline
    client = TestClient(app, base_url="http://localhost")
    client.post("/ingest", content="ts=2026-11-20T10:00:01Z host=a metric=cpu_pct value=40")
    monkeypatch.setattr(pipe.policy, "apply", lambda payload: type("D", (), {"blocked": True, "payload": payload})())
    pipe.flush(force=True)
    s = pipe.stages()
    assert s["rejected_before_queue"]["blocked_by_policy"] == 1 and s["queued"] == 0 and all(c["ok"] for c in s["checks"])


def test_the_stages_view_is_local_only_and_the_page_renders_it_safely():
    app = make()
    js, html = (UI / "app.js").read_text(encoding="utf-8"), (UI / "index.html").read_text(encoding="utf-8")
    assert "stages-body" in html and "/local/stages" in js and ".innerHTML" not in js
    from collector.tests.test_egress_ui import remote

    assert remote(app, "GET", "/local/stages").status_code == 403
    assert "format" not in json.dumps(TestClient(app, base_url="http://localhost").get("/local/stages").json()["checks"])
