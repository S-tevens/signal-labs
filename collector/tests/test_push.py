"""The push gateway: who may send, and every way the organizers' tools can send."""
import base64
import gzip
import json
import time

from fastapi.testclient import TestClient

from collector.config import Config
from collector.main import create_app
from collector.tests.test_egress_ui import remote

TOKEN = "push-token-0123456789"
NOW = int(time.time())


def make(**kw):
    cfg = Config(data_dir=":memory:", host_telemetry=False, saas_url="http://127.0.0.1:1", grace_s=0, **kw)
    app = create_app(cfg, run_sender=False)
    return app, TestClient(app, base_url="http://localhost")


def sent(app):
    app.state.pipeline.flush(force=True)
    return [e["payload"] for e in app.state.store.recent_egress(200)]


def metrics(app):
    return {(p["metric"]["name"], round(p["metric"]["value"], 1)) for p in sent(app) if "metric" in p}


LINE = f"ts={NOW} host=h metric=cpu_pct value=44"


# ---- the guard ----
def test_with_no_token_configured_the_local_default_stays_open():
    app, c = make()
    assert c.post("/ingest", content=LINE).status_code == 200 and app.state.guard.open


def test_a_token_is_required_on_every_push_route_and_a_wrong_one_is_refused():
    app, c = make(ingest_token=TOKEN)
    for path in ("/ingest", "/write", "/api/v2/write", "/v1/metrics"):
        assert c.post(path, content="x").status_code == 401, path
        assert c.post(path, content="x", headers={"Authorization": "Bearer wrong-token"}).status_code == 401, path
    assert c.get("/healthz").status_code == 200  # health stays open


def test_the_token_is_accepted_the_ways_common_agents_send_it():
    app, c = make(ingest_token=TOKEN)
    basic = "Basic " + base64.b64encode(f"anyuser:{TOKEN}".encode()).decode()
    for headers in ({"Authorization": f"Bearer {TOKEN}"}, {"Authorization": f"Token {TOKEN}"}, {"X-Ingest-Token": TOKEN}, {"Authorization": basic}):
        assert c.post("/ingest", content=LINE, headers=headers).status_code == 200, headers


def test_only_allowed_addresses_may_push_over_http():
    app, _ = make(ingest_token=TOKEN, ingest_allow="10.0.0.0/8, 192.168.1.5")
    assert remote(app, "POST", "/ingest", content=LINE, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 403  # 203.0.113.9
    app2, _ = make(ingest_allow="203.0.113.0/24")
    assert remote(app2, "POST", "/ingest", content=LINE).status_code == 200


def test_the_local_views_stay_local_even_with_a_valid_token():
    app, _ = make(ingest_token=TOKEN)
    assert remote(app, "GET", "/local/raw", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 403


def test_the_token_is_not_part_of_the_configuration_fingerprint(tmp_path):
    from collector.sender import config_hash

    assert config_hash(Config(data_dir=tmp_path, ingest_token="a")) == config_hash(Config(data_dir=tmp_path, ingest_token="b"))


# ---- every way in ----
def test_ingest_takes_lines_a_json_array_and_ndjson():
    app, c = make()
    c.post("/ingest", content=json.dumps([{"ts": NOW, "host": "a", "metric": "cpu_pct", "value": 11}, {"ts": NOW, "host": "a", "metric": "mem_pct", "value": 22}]))
    c.post("/ingest", content=f'{{"ts":{NOW},"host":"b","metric":"disk_pct","value":33}}\n{{"ts":{NOW},"host":"b","metric":"latency_ms","value":44}}')
    assert {("cpu_pct", 11.0), ("mem_pct", 22.0), ("disk_pct", 33.0), ("latency_ms", 44.0)} <= metrics(app)


def test_gzip_bodies_are_accepted_and_a_zip_bomb_is_refused():
    app, c = make(max_ingest_bytes=5000)
    ok = c.post("/ingest", content=gzip.compress(LINE.encode()), headers={"Content-Encoding": "gzip"})
    assert ok.status_code == 200 and ("cpu_pct", 44.0) in metrics(app)
    bomb = c.post("/ingest", content=gzip.compress(b"a" * 2_000_000), headers={"Content-Encoding": "gzip"})
    assert bomb.status_code == 413 and "decompressed" in bomb.json()["detail"]
    assert c.post("/ingest", content=b"not gzip at all", headers={"Content-Encoding": "gzip"}).status_code == 400
    assert c.post("/ingest", content=LINE, headers={"Content-Encoding": "br"}).status_code == 415


def test_a_body_over_the_limit_is_refused_before_it_is_read():
    _, c = make(max_ingest_bytes=100)
    assert c.post("/ingest", content="x" * 500).status_code == 413


def test_telegrafs_influx_output_works_on_both_write_paths_and_answers_204():
    app, c = make()
    ns = NOW * 1_000_000_000
    r1 = c.post("/write?db=telegraf", content=f"cpu,host=srv-3 usage_user=41.5 {ns}\nmem,host=srv-3 used_percent=58.2 {ns}")
    r2 = c.post("/api/v2/write?org=o&bucket=b", content=f"cpu,host=srv-4 usage_user=12.5 {ns}")
    assert r1.status_code == r2.status_code == 204 and {("cpu_pct", 41.5), ("mem_pct", 58.2), ("cpu_pct", 12.5)} <= metrics(app)


OTLP = {"resourceMetrics": [{"resource": {"attributes": [{"key": "host.name", "value": {"stringValue": "otel-1"}}]},
                            "scopeMetrics": [{"metrics": [
                                {"name": "system.cpu.utilization", "gauge": {"dataPoints": [{"asDouble": 0.37, "timeUnixNano": str(NOW * 10**9)}]}},
                                {"name": "system.memory.utilization", "gauge": {"dataPoints": [{"asDouble": 0.5, "timeUnixNano": str(NOW * 10**9)}]}},
                                {"name": "latency_ms", "sum": {"dataPoints": [{"asInt": "120", "timeUnixNano": str(NOW * 10**9)}]}},
                                {"name": "request.duration", "histogram": {"dataPoints": [{"count": "3"}]}}]}]}]}


def test_opentelemetry_json_metrics_are_converted_with_the_resource_host():
    app, c = make(ingest_token=TOKEN)
    r = c.post("/v1/metrics", json=OTLP, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.json() == {"partialSuccess": {}}
    got = sent(app)
    assert {("cpu_pct", 37.0), ("mem_pct", 50.0), ("latency_ms", 120.0)} <= {(p["metric"]["name"], round(p["metric"]["value"], 1)) for p in got if "metric" in p}
    assert not any("request" in json.dumps(p) for p in got)  # histograms are skipped, not guessed


def test_otlp_protobuf_and_garbage_get_clear_errors():
    _, c = make()
    assert c.post("/v1/metrics", content=b"\x0a\x00", headers={"Content-Type": "application/x-protobuf"}).status_code == 415
    assert c.post("/v1/metrics", content="not json").status_code == 400


def test_a_secret_pushed_in_any_form_never_reaches_a_payload():
    app, c = make()
    c.post("/ingest", content='{"host":"h","metric":"cpu_pct","value":50,"ts":%d,"note":"password=Hunter2! alice@corp.com"}' % NOW)
    c.post("/write", content=f"cpu,host=h,owner=alice@corp.com usage_user=51 {NOW * 10**9}")
    blob = json.dumps(sent(app))
    assert "Hunter2" not in blob and "alice@corp.com" not in blob


def test_the_stages_view_counts_what_was_pushed():
    app, c = make()
    c.post("/ingest", content=LINE + "\n" + LINE.replace("value=44", "value=45"))
    s = c.get("/local/stages").json()
    assert s["received"] == 2 and all(x["ok"] for x in s["checks"])


# ---- the UDP and TCP lines respect the allow-list ----
def test_syslog_listeners_refuse_sources_outside_the_allow_list():
    import asyncio
    import socket

    from collector.adapters import Adapters
    from collector.outbox import LocalStore
    from collector.pipeline import Pipeline

    s = socket.socket(socket.SOCK_DGRAM and socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    async def go(allow):
        cfg = Config(data_dir=":memory:", host_telemetry=False, grace_s=0, udp_syslog_port=port, ingest_allow=allow)
        pipe = Pipeline(cfg, LocalStore(":memory:"))
        a = Adapters(cfg, pipe)
        await a.start()
        loop = asyncio.get_running_loop()
        t, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, remote_addr=("127.0.0.1", port))
        t.sendto(LINE.encode())
        await asyncio.sleep(0.4)
        t.close()
        await a.stop()
        return pipe.counters["adapter:udp"], pipe.counters["push_refused"]

    assert asyncio.run(go("")) == (1, 0)
    assert asyncio.run(go("10.0.0.0/8")) == (0, 1)
