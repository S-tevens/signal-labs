import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from collector.config import Config
from collector.main import create_app
from collector.outbox import LocalStore
from collector.pipeline import Pipeline
from collector.schema import Payload

from .test_egress_ui import remote

MIB = 1 << 20


def pl(i):
    return {"payload_id": f"p{i:06d}", "n": i}


# ---- age-based retention ----
def test_old_raw_records_are_deleted_on_schedule_and_fresh_ones_kept():
    store = LocalStore(":memory:")
    for _ in range(3):
        store.add_raw("old line", [])
    t = time.time()
    assert store.apply_retention(60, 1e9, now=t + 30)["raw_purged"] == 0  # 30 s old: inside the 60 s window
    done = store.apply_retention(60, 1e9, now=t + 120)  # 120 s old: expired
    assert done["raw_purged"] == 3 and store.recent_raw() == []
    assert store.retention_status()["totals"]["purged_raw_total"] == 3


def test_delivered_transfer_records_expire_but_undelivered_payloads_never_do():
    store = LocalStore(":memory:")
    for i in range(3):
        store.enqueue(pl(i), [], [])
    store.mark_sent(["p000000", "p000001"])
    done = store.apply_retention(1e9, 100, now=time.time() + 1_000_000)
    assert done["outbox_purged"] == 2
    assert store.depth() == 1 and store.counts() == {"pending": 1}  # still waiting for delivery, so it stays


def test_rejected_records_expire_too():
    store = LocalStore(":memory:")
    store.enqueue(pl(1), [], [])
    store.mark_rejected("p000001", "HTTP 422")
    assert store.apply_retention(1e9, 10, now=time.time() + 100)["outbox_purged"] == 1


# ---- write-time caps: a flood cannot outrun the timer ----
def test_raw_row_cap_holds_at_write_time():
    store = LocalStore(":memory:", raw_max_rows=100)
    last = 0
    for i in range(1000):
        last = store.add_raw(f"line {i}", [])
    rows = store.retention_status()["usage"]["raw_rows"]
    assert 100 <= rows <= 199  # at most one check interval over the cap, never the 1000 written
    assert store.recent_raw(1)[0]["id"] == last  # the newest record survives
    assert store.retention_status()["totals"]["trimmed_raw_total"] >= 800


def test_full_outbox_drops_the_oldest_pending_first_and_counts_every_drop():
    store = LocalStore(":memory:", outbox_max_pending=100)
    for i in range(500):
        store.enqueue(pl(i), [], [])
    assert store.depth() <= 149  # cap plus at most one check interval
    store.apply_retention(1e9, 1e9)
    assert store.depth() == 100  # exactly the cap once the scheduled run has trimmed
    kept = {p["payload_id"] for p in store.pending(1000)}
    assert "p000499" in kept and "p000000" not in kept  # newest kept, oldest dropped
    assert store.retention_status()["totals"]["dropped_overflow_total"] == 400  # nothing lost without a count


def test_database_size_is_bounded_by_the_byte_cap(tmp_path):
    store = LocalStore(tmp_path, raw_max_rows=10_000_000, max_db_bytes=2 * MIB)
    blob = "x" * 10_000
    for _ in range(3000):  # 30 MB of raw lines against a 2 MiB cap
        store.add_raw(blob, [])
    st = store.retention_status()["usage"]
    assert st["live_bytes"] < 4 * MIB, st
    assert st["disk_bytes"] < 16 * MIB, st  # including the write-ahead log
    assert st["raw_rows"] < 1000


# ---- input limits ----
def test_an_oversize_line_is_dropped_without_being_parsed(monkeypatch):
    cfg = Config(data_dir=":memory:", host_telemetry=False, max_line_chars=1000)
    store = LocalStore(":memory:")
    p = Pipeline(cfg, store)
    monkeypatch.setattr("collector.pipeline.parse_line", lambda line: (_ for _ in ()).throw(AssertionError("must not parse")))
    out = p.process("x" * 5000 + " password=Hunter2!")
    assert out["status"] == "dropped_oversize" and p.counters["oversize"] == 1
    assert store.depth() == 0
    assert len(store.recent_raw(1)[0]["text"]) < 1200  # a short marker, not 5 KB of attacker data
    monkeypatch.undo()
    assert p.process('{"kind":"metric","host":"h","name":"cpu_pct","value":5}')["status"] == "aggregated"  # still working


def test_a_request_over_the_body_limit_is_refused_with_413():
    app = create_app(Config(data_dir=":memory:", host_telemetry=False, max_ingest_bytes=1000, saas_url="http://127.0.0.1:1"), run_sender=False)
    client = TestClient(app)
    assert client.post("/ingest", content=b"a=1 b=2\n").status_code == 200
    assert client.post("/ingest", content=b"a" * 5000).status_code == 413  # declared length too big
    assert client.post("/ingest", content=(b"a" * 100 for _ in range(50))).status_code == 413  # chunked: no length to check


# ---- losses are reported, not silent ----
def test_dropped_payloads_are_reported_to_the_platform_exactly_once():
    cfg = Config(data_dir=":memory:", host_telemetry=False)
    store = LocalStore(":memory:", outbox_max_pending=10)
    pipeline = Pipeline(cfg, store)
    for i in range(200):
        store.enqueue(pl(i), [], [])
    store.apply_retention(1e9, 1e9)
    lost = store.take_unreported_drops()
    assert lost == 190
    assert pipeline.emit_collector_event("service_state", "warning", lost, "buffer overflow dropped payloads")
    assert store.take_unreported_drops() == 0  # reported once, not on every run

    event = [e for e in store.recent_egress(50) if "event" in e["payload"]][0]
    Payload.model_validate(event["payload"])  # a real, valid payload under the frozen schema
    assert event["payload"]["event"] == {"category": "service_state", "severity": "warning", "count": 190, "summary": "buffer overflow dropped payloads"}
    assert event["raw_ids"] == []  # no raw record is behind it


def test_counters_survive_a_restart(tmp_path):
    store = LocalStore(tmp_path, outbox_max_pending=5)
    for i in range(60):
        store.enqueue(pl(i), [], [])
    store.apply_retention(1e9, 1e9)
    before = store.retention_status()["totals"]
    reopened = LocalStore(tmp_path, outbox_max_pending=5)
    assert reopened.retention_status()["totals"] == before and before["dropped_overflow_total"] == 55


# ---- the whole thing together ----
def test_a_flood_through_the_pipeline_cannot_fill_the_disk(tmp_path):
    cfg = Config(data_dir=tmp_path, host_telemetry=False, window_s=5, grace_s=0, raw_max_rows=200, outbox_max_pending=300, max_db_bytes=2 * MIB)
    store = LocalStore(tmp_path, raw_max_rows=200, outbox_max_pending=300, max_db_bytes=2 * MIB)
    pipeline = Pipeline(cfg, store)
    base = 1_800_000_000
    for i in range(10_000):  # many sources and windows, so many payloads
        host = f"host-{i % 400}"
        pipeline.process(json.dumps({"kind": "metric", "host": host, "name": "cpu_pct", "value": i % 100, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base + i * 7))}))
        if i % 50 == 0:
            pipeline.flush(force=True)
    pipeline.flush(force=True)
    store.apply_retention(1e9, 1e9)
    st = store.retention_status()
    assert st["usage"]["raw_rows"] <= 200 + 100  # capped (one check interval of slack)
    assert st["usage"]["outbox"].get("pending", 0) <= 300
    assert st["usage"]["disk_bytes"] < 16 * MIB
    assert st["totals"]["dropped_overflow_total"] > 0  # the overflow was real, and was counted


def test_the_retention_job_runs_inside_the_app_and_the_endpoint_is_local_only():
    cfg = Config(data_dir=":memory:", host_telemetry=False, saas_url="http://127.0.0.1:1", raw_retention_s=0, retention_interval_s=0.05)
    app = create_app(cfg, run_sender=False)
    with TestClient(app) as client:
        client.post("/ingest", content="Nov 20 09:15:01 web-1 app[1]: hello")
        deadline = time.time() + 5
        status = {}
        while time.time() < deadline:
            status = client.get("/local/retention").json()
            if status["totals"]["purged_raw_total"] >= 1:
                break
            time.sleep(0.1)
        assert status["totals"]["purged_raw_total"] >= 1 and status["usage"]["raw_rows"] == 0  # expired and deleted by the timer
        assert {"usage", "limits", "totals", "policy"} <= set(status)
        assert status["policy"]["undelivered_payloads"].startswith("kept until delivered")
    assert remote(app, "GET", "/local/retention").status_code == 403
