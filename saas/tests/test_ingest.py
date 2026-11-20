import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saas.main import create_app

TENANTS = str(Path(__file__).resolve().parents[1] / "config" / "tenants.json")
ACME = {"key": "key-acme-1", "secret": "dev-secret-acme", "tenant": "t-acme", "collector": "col-blr-01", "dash": "dash-acme"}
GLOBEX = {"key": "key-globex-1", "secret": "dev-secret-globex", "tenant": "t-globex", "collector": "col-fra-01", "dash": "dash-globex"}


@pytest.fixture()
def client():
    return TestClient(create_app("sqlite:///:memory:", TENANTS))


def payload(who=ACME, ts=None, **over):
    p = {
        "payload_id": str(uuid.uuid4()),
        "tenant_ref": who["tenant"],
        "collector_id": who["collector"],
        "source_id": "src_9fa2c1d3e4f5",
        "region": "in",
        "event_ts_utc": (ts or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_tz": "Asia/Kolkata",
        "window_s": 5,
        "metric": {"name": "cpu_pct", "value": 42.0, "unit": "%"},
        "health_state": "Good",
        "collector_version": "0.1.0",
    }
    p.update(over)
    return p


def post(client, payloads, who=ACME, sign=True, path="/v1/ingest", body=None):
    raw = body if body is not None else json.dumps({"payloads": payloads}).encode()
    sig = hmac.new(who["secret"].encode(), raw, hashlib.sha256).hexdigest() if sign else "0" * 64
    return client.post(path, content=raw, headers={"X-Collector-Key": who["key"], "X-Signature": sig})


def get(client, path, who=ACME):
    return client.get(path, headers={"X-Dashboard-Token": who["dash"]})


def test_accepts_valid_payload(client):
    p = payload()
    r = post(client, [p])
    assert r.status_code == 200 and r.json()["accepted"] == [p["payload_id"]]


def test_bad_signature_and_unknown_key_are_401(client):
    assert post(client, [payload()], sign=False).status_code == 401
    raw = b'{"payloads":[]}'
    r = client.post("/v1/ingest", content=raw, headers={"X-Collector-Key": "nope", "X-Signature": "x"})
    assert r.status_code == 401


def test_duplicate_payload_id_is_not_stored_twice(client):
    p = payload()
    assert post(client, [p]).json()["accepted"] == [p["payload_id"]]
    again = post(client, [p]).json()
    assert again["duplicate"] == [p["payload_id"]] and again["accepted"] == []
    assert client.app.state.store.count_events("t-acme") == 1


def test_batch_with_duplicate_inside_still_stores_the_rest(client):
    a, b = payload(), payload()
    post(client, [a])
    r = post(client, [a, b]).json()
    assert r["duplicate"] == [a["payload_id"]] and r["accepted"] == [b["payload_id"]]


def test_extra_field_is_rejected(client):
    p = payload(raw_message="password=hunter2")
    r = post(client, [p]).json()
    assert r["accepted"] == [] and r["rejected"][0]["payload_id"] == p["payload_id"]


def test_payload_claiming_another_tenant_is_rejected(client):
    p = payload(GLOBEX)  # globex payload sent with acme credentials
    r = post(client, [p], who=ACME).json()
    assert r["accepted"] == [] and "credential" in r["rejected"][0]["reason"]


def test_tenants_cannot_see_each_other(client):
    post(client, [payload(ACME)], who=ACME)
    post(client, [payload(GLOBEX)], who=GLOBEX)
    acme_fleet = get(client, "/v1/fleet", ACME).json()
    globex_fleet = get(client, "/v1/fleet", GLOBEX).json()
    assert [c["collector_id"] for c in acme_fleet] == ["col-blr-01"]
    assert [c["collector_id"] for c in globex_fleet] == ["col-fra-01"]
    assert len(get(client, "/v1/metrics", ACME).json()) == 1
    assert get(client, "/v1/fleet", {"dash": "wrong"}).status_code == 401


def test_out_of_order_events_are_returned_in_event_time_order(client):
    now = datetime.now(timezone.utc)
    newer = payload(ts=now - timedelta(seconds=5))
    older = payload(ts=now - timedelta(seconds=60))
    post(client, [newer])
    post(client, [older])  # arrives second, happened first
    times = [m["event_ts_utc"] for m in get(client, "/v1/metrics", ACME).json()]
    assert times == sorted(times) and len(times) == 2


def test_future_and_non_utc_timestamps_rejected(client):
    future = payload(ts=datetime.now(timezone.utc) + timedelta(hours=1))
    ist = payload(event_ts_utc="2026-11-20T09:15:00+05:30")
    r = post(client, [future, ist]).json()
    assert r["accepted"] == [] and len(r["rejected"]) == 2


def test_heartbeat_updates_fleet(client):
    body = json.dumps({"collector_id": "col-blr-01", "version": "0.1.0", "buffer_depth": 3, "config_hash": "x"}).encode()
    assert post(client, [], body=body, path="/v1/heartbeat").status_code == 200
    fleet = get(client, "/v1/fleet").json()
    assert fleet[0]["state"] == "Good" and fleet[0]["buffer_depth"] == 3
