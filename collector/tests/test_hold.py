"""Hold and release (E18): payloads wait visibly, carry a fixed digest, and leave only after release."""
import asyncio
import json
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from collector.config import Config
from collector.main import create_app
from collector.outbox import digest_of
from collector.tests.test_egress_ui import SECRET_LINE, remote

LOCAL = {"X-Requested-With": "local-ui"}


def make():
    cfg = Config(data_dir=":memory:", host_telemetry=False, saas_url="http://127.0.0.1:1", grace_s=0)
    return create_app(cfg, run_sender=False)


def queue_secret(app):
    client = TestClient(app, base_url="http://localhost")
    client.post("/ingest", content=SECRET_LINE)
    app.state.pipeline.flush(force=True)
    return client, app.state.store.recent_egress(1)[0]


def deliver(app):
    """Run one send attempt against a stand-in SaaS that accepts everything. Returns the request bodies it saw."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"accepted": [p["payload_id"] for p in body], "duplicate": [], "conflict": []})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await app.state.sender.send_once(c)

    asyncio.run(go())
    return seen


def test_held_payloads_wait_in_the_outbox_and_show_as_pending_without_the_secret():
    app = make()
    client, item = queue_secret(app)
    assert client.post("/local/hold", headers=LOCAL).json()["held"] is True
    assert deliver(app) == []  # nothing left the building
    pending = app.state.store.egress_one(item["payload_id"])
    assert pending["status"] == "pending"
    assert "Hunter2" not in json.dumps(pending["payload"]) and "alice@corp.com" not in json.dumps(pending["payload"])
    buf = client.get("/local/buffer").json()
    assert buf["hold"]["held"] and buf["pending"] >= 1 and buf["oldest_pending_age_s"] is not None


def test_release_sends_the_same_id_with_the_same_digest():
    app = make()
    client, item = queue_secret(app)
    client.post("/local/hold", headers=LOCAL)
    before = app.state.store.egress_one(item["payload_id"])
    client.post("/local/release", headers=LOCAL)
    sent = deliver(app)
    assert [p["payload_id"] for b in sent for p in b] == [item["payload_id"]]
    assert digest_of(sent[0][0]) == before["digest"]
    after = app.state.store.egress_one(item["payload_id"])
    assert after["status"] == "sent" and after["sent_at"] and after["digest"] == before["digest"]


def test_the_hold_releases_itself_after_the_maximum_time():
    app = make()
    client, item = queue_secret(app)
    app.state.sender.hold_max_s = 0.2
    client.post("/local/hold", headers=LOCAL)
    assert deliver(app) == []
    time.sleep(0.3)
    assert len(deliver(app)) == 1
    state = client.get("/local/buffer").json()["hold"]
    assert state["held"] is False and "auto-release" in state["last_release"]["reason"]


def test_the_digest_is_fixed_at_queue_time_and_an_altered_body_is_never_sent():
    app = make()
    client, item = queue_secret(app)
    store = app.state.store
    body = json.loads(store._db.execute("SELECT body FROM outbox WHERE payload_id=?", (item["payload_id"],)).fetchone()["body"])
    body["collector_version"] = "tampered"
    store._db.execute("UPDATE outbox SET body=? WHERE payload_id=?", (json.dumps(body), item["payload_id"]))
    store._db.commit()
    assert deliver(app) == []
    assert store.egress_one(item["payload_id"])["status"] == "rejected"
    assert "altered" in (app.state.sender.last_error or "")


def test_hold_and_release_need_the_local_page_header_and_a_local_host():
    app = make()
    client = TestClient(app, base_url="http://localhost")
    assert client.post("/local/hold").status_code == 403  # a request without the header, as from another site
    assert client.post("/local/hold", headers={"X-Requested-With": "XMLHttpRequest"}).status_code == 403
    assert TestClient(app, base_url="http://evil.example").post("/local/hold", headers=LOCAL).status_code == 403
    assert remote(app, "POST", "/local/hold", headers=LOCAL).status_code == 403  # another machine
    assert app.state.sender.hold_state()["held"] is False


def test_holding_twice_keeps_the_original_start_and_release_when_not_held_is_harmless():
    app = make()
    client = TestClient(app, base_url="http://localhost")
    first = client.post("/local/hold", headers=LOCAL).json()["held_since_utc"]
    assert client.post("/local/hold", headers=LOCAL).json()["held_since_utc"] == first
    client.post("/local/release", headers=LOCAL)
    assert client.post("/local/release", headers=LOCAL).json()["held"] is False


def test_the_panel_offers_hold_and_shows_digest_and_sent_time():
    ui = Path(__file__).resolve().parents[1] / "ui"
    js, html = (ui / "app.js").read_text(encoding="utf-8"), (ui / "index.html").read_text(encoding="utf-8")
    assert "hold-toggle" in html and "X-Requested-With" in js and "SHA-256" in js and "sent_at" in js
    assert ".innerHTML" not in js and "insertAdjacentHTML" not in js  # the comment may mention it; code may not use it
