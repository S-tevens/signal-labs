"""Pull inputs and the stream checker (E26): connect out to a stream, survive drops, and judge an unknown sample."""
import asyncio
import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest

from collector import pull
from collector.config import Config
from collector.outbox import LocalStore
from collector.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("stream_check", ROOT / "simulator" / "stream_check.py")
sc = importlib.util.module_from_spec(_spec)
sys.modules["stream_check"] = sc
_spec.loader.exec_module(sc)

LINE = "ts=2026-11-21T10:00:{n:02d}Z host=h metric=cpu_pct value={v}"  # keep n at least 10 apart so readings are not averaged


def make(**kw):
    cfg = Config(data_dir=":memory:", host_telemetry=False, grace_s=0, **kw)
    store = LocalStore(":memory:")
    return Pipeline(cfg, store), store, cfg


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def values(store):
    return sorted(e["payload"]["metric"]["value"] for e in store.recent_egress(100) if "metric" in e["payload"])


async def serve(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", free_port())
    return server, server.sockets[0].getsockname()[1]


async def settle(sources, want, timeout=6.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if sum(s.lines for s in sources) >= want:
            return
        await asyncio.sleep(0.1)


# ---- pure helpers ----
def test_json_arrays_become_one_record_per_line_and_other_text_is_untouched():
    assert pull.expand('[{"a":1},{"a":2}]').splitlines() == ['{"a":1}', '{"a":2}']
    assert pull.expand("plain line") == "plain line" and pull.expand("[not json") == "[not json"


def test_server_sent_events_keep_only_the_data():
    assert pull.sse_payload("data: ts=1 host=h") == "ts=1 host=h"
    assert pull.sse_payload("event: tick") is None and pull.sse_payload(": keep-alive") is None and pull.sse_payload("id: 7") is None
    assert pull.sse_payload("a plain line") == "a plain line"


def test_auth_headers_and_the_target_shown_never_expose_a_secret():
    assert pull.auth_headers("Authorization: Bearer abc") == {"Authorization": "Bearer abc"}
    assert pull.auth_headers("X-Api-Key: k1") == {"X-Api-Key": "k1"}
    assert pull.auth_headers("abc123") == {"Authorization": "Bearer abc123"} and pull.auth_headers("") == {}
    assert pull.shown("https://user:pw@feed.example:8443/stream?token=SECRET") == "https://feed.example:8443/stream"
    assert "SECRET" not in pull.shown("https://x/y?token=SECRET") and pull.shown("10.0.0.5:9000") == "tcp://10.0.0.5:9000"


# ---- live connections ----
def test_a_tcp_stream_is_pulled_and_reconnects_after_the_server_drops():
    async def go():
        conns = []

        async def handler(reader, writer):
            conns.append(1)
            writer.write((LINE.format(n=10 * len(conns), v=10 * len(conns)) + "\n").encode())
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()  # drop: the collector must come back

        server, port = await serve(handler)
        pipe, store, cfg = make(stream_tcp=f"127.0.0.1:{port}")
        pa = pull.PullAdapters(cfg, pipe)
        await pa.start()
        await settle(pa.sources, 2, timeout=8)
        await pa.stop()
        server.close()
        pipe.flush(force=True)
        return pa.status()[0], values(store)

    status, vals = asyncio.run(go())
    assert vals == [10.0, 20.0] and status["reconnects"] >= 1 and status["lines_received"] == 2


def test_an_http_stream_with_server_sent_events_is_pulled():
    async def go():
        async def handler(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
            writer.write(b": hello\n\nevent: tick\ndata: " + LINE.format(n=1, v=33).encode() + b"\n\n")
            await writer.drain()
            await asyncio.sleep(0.2)
            writer.close()

        server, port = await serve(handler)
        pipe, store, cfg = make(stream_url=f"http://127.0.0.1:{port}/feed?token=SECRET", stream_auth="Bearer SECRET")
        pa = pull.PullAdapters(cfg, pipe)
        await pa.start()
        await settle(pa.sources, 1)
        await pa.stop()
        server.close()
        pipe.flush(force=True)
        return pa.status()[0], values(store)

    status, vals = asyncio.run(go())
    assert vals == [33.0] and "SECRET" not in json.dumps(status) and status["target"].endswith("/feed")


def test_polling_a_json_array_endpoint_and_sending_the_auth_header():
    async def go():
        seen = []

        async def handler(reader, writer):
            head = (await reader.readuntil(b"\r\n\r\n")).decode()
            seen.append("authorization: bearer s3cret" in head.lower())
            rows = [{"ts": "2026-11-21T10:00:01Z", "host": "h", "metric": "cpu_pct", "value": 51},
                    {"ts": "2026-11-21T10:00:01Z", "host": "h", "metric": "mem_pct", "value": 52}]
            body = json.dumps(rows).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
            await writer.drain()
            writer.close()

        server, port = await serve(handler)
        pipe, store, cfg = make(stream_url=f"http://127.0.0.1:{port}/data", stream_poll_s=0.2, stream_auth="s3cret")
        pa = pull.PullAdapters(cfg, pipe)
        await pa.start()
        await settle(pa.sources, 2)
        await pa.stop()
        server.close()
        pipe.flush(force=True)
        return seen, {e["payload"]["metric"]["name"] for e in store.recent_egress(50) if "metric" in e["payload"]}

    seen, names = asyncio.run(go())
    assert seen and all(seen) and names == {"cpu_pct", "mem_pct"}


def test_a_websocket_stream_is_pulled():
    websockets = pytest.importorskip("websockets")

    async def go():
        async def handler(ws):
            await ws.send(LINE.format(n=1, v=61))
            await ws.send(json.dumps([{"ts": "2026-11-21T10:00:30Z", "host": "h", "metric": "cpu_pct", "value": 62}]))
            await asyncio.sleep(0.3)

        port = free_port()
        async with websockets.serve(handler, "127.0.0.1", port):
            pipe, store, cfg = make(stream_ws=f"ws://127.0.0.1:{port}/x")
            pa = pull.PullAdapters(cfg, pipe)
            await pa.start()
            await settle(pa.sources, 2)
            await pa.stop()
        pipe.flush(force=True)
        return values(store)

    assert asyncio.run(go()) == [61.0, 62.0]


def test_a_dead_target_is_reported_not_fatal():
    async def go():
        pipe, _, cfg = make(stream_tcp=f"127.0.0.1:{free_port()}")
        pa = pull.PullAdapters(cfg, pipe)
        await pa.start()
        for _ in range(100):  # Windows can take a second or more to report a refused connection
            if pa.sources[0].reconnects:
                break
            await asyncio.sleep(0.1)
        await pa.stop()
        return pa.status()[0]

    s = asyncio.run(go())
    assert s["state"] == "retrying" and s["lines_received"] == 0 and s["last_error"]


# ---- the checker ----
def test_the_checker_says_ready_for_a_sample_that_maps():
    res = sc.analyse(["ts=2026-11-21T10:00:01Z host=a metric=cpu_pct value=40", '{"hostname":"b","cpu_ratio":0.4,"latency_s":0.05}'])
    assert res["verdict"] == "READY" and res["records_accepted"] >= 3


def test_the_checker_finds_unmapped_fields_and_suggests_the_mapping_with_units():
    res = sc.analyse(['{"node":"n1","cpu_usage":55,"net_rx_kbps":84000,"response_time_s":0.2,"queue_len":4}'])
    assert res["verdict"] == "NEEDS MAPPING"
    assert res["suggested_mapping"]["net_rx_kbps"] == "{name: bandwidth_mbps, scale: 0.001}"
    assert res["suggested_mapping"]["queue_len"] is None
    assert "net_rx_kbps" in res["numeric_fields_ignored"]


def test_the_checker_reports_sensitive_patterns_and_missing_times_without_failing():
    res = sc.analyse(["Nov 21 10:00:02 srv sshd[1]: opened for alice password=Hunter2!"])
    assert "password" in res["sensitive_patterns_found"] and res["records_without_a_time"] == 1 and res["verdict"] == "READY"


def test_a_sample_with_nothing_usable_is_flagged():
    assert sc.analyse(['{"kind":"metric","name":"zzz","value":"abc","host":"h"}'])["verdict"] == "NOTHING USABLE"
