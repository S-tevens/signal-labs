"""Failover proxy (scripts/lb.py), exercised against real upstream servers."""
import asyncio
import hashlib
import importlib.util
import socket
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

_spec = importlib.util.spec_from_file_location("lb", Path(__file__).resolve().parents[2] / "scripts" / "lb.py")
lb = importlib.util.module_from_spec(_spec)
sys.modules["lb"] = lb  # dataclasses resolves annotations through sys.modules, so register before running the module
_spec.loader.exec_module(lb)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def replica_app(name, seen):
    app = FastAPI()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "replica": name}

    @app.post("/v1/ingest")
    async def ingest(request: Request):
        body = await request.body()
        seen.append((name, body))
        return {"replica": name, "sha256": hashlib.sha256(body).hexdigest(), "len": len(body),
                "sig": request.headers.get("x-signature"), "key": request.headers.get("x-collector-key"),
                "encoding": request.headers.get("content-encoding"), "query": request.url.query}

    @app.get("/echo")
    async def echo(request: Request):
        return {"replica": name, "query": request.url.query, "auth": request.headers.get("authorization")}

    @app.get("/unavailable")
    async def unavailable():
        from fastapi.responses import JSONResponse
        return JSONResponse({"replica": name}, status_code=503)

    @app.get("/denied")
    async def denied():
        from fastapi.responses import JSONResponse
        seen.append((name, b"denied"))
        return JSONResponse({"replica": name}, status_code=401)

    @app.get("/stream")
    async def stream():
        async def gen():
            for i in range(3):
                yield f"chunk{i};".encode()
                await asyncio.sleep(0.05)
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


class Replica:
    def __init__(self, name, port=None):
        self.name, self.port, self.seen = name, port or free_port(), []
        self.server = self.thread = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        cfg = uvicorn.Config(replica_app(self.name, self.seen), host="127.0.0.1", port=self.port, log_level="error")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        end = time.time() + 10
        while not self.server.started and time.time() < end:
            time.sleep(0.05)
        assert self.server.started
        return self

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@contextmanager
def two_replicas():
    a, b = Replica("A").start(), Replica("B").start()
    try:
        yield a, b
    finally:
        for r in (a, b):
            try:
                r.stop()
            except Exception:
                pass


def run(app, steps, client=None):
    """Drive the proxy app in-process, in one event loop (its HTTP client is bound to that loop)."""

    async def go():
        transport = httpx.ASGITransport(app=app, client=client or ("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://lb") as c:
            try:
                return await steps(c, app.state.balancer)
            finally:
                await app.state.balancer.client.aclose()

    return asyncio.run(go())


def test_round_robin_uses_both_replicas():
    with two_replicas() as (a, b):
        async def steps(c, bal):
            return [(await c.get("/echo")).json()["replica"] for _ in range(6)]

        who = run(lb.create_proxy([a.url, b.url]), steps)
        assert set(who) == {"A", "B"} and who.count("A") == who.count("B") == 3


def test_exact_bytes_and_auth_headers_survive_the_hop():
    """The collector's HMAC covers the exact body, so any change would turn into a 401 at the SaaS."""
    with two_replicas() as (a, b):
        body = b'{"payloads": [ {"payload_id":"x" } ]}\r\n\x00\xff binary \t  tail  '  # odd spacing and non-UTF-8 bytes
        async def steps(c, bal):
            return (await c.post("/v1/ingest?x=1&y=%20z", content=body,
                                 headers={"X-Signature": "abc123", "X-Collector-Key": "key-1", "Content-Encoding": "identity"})).json()

        got = run(lb.create_proxy([a.url, b.url]), steps)
        assert got["sha256"] == hashlib.sha256(body).hexdigest() and got["len"] == len(body)
        assert got["sig"] == "abc123" and got["key"] == "key-1" and got["encoding"] == "identity"
        assert got["query"] == "x=1&y=%20z"


def test_authorization_header_reaches_the_replica():
    with two_replicas() as (a, b):
        async def steps(c, bal):
            return (await c.get("/echo", headers={"Authorization": "Bearer dash-acme"})).json()

        assert run(lb.create_proxy([a.url]), steps)["auth"] == "Bearer dash-acme"


def test_killing_a_replica_loses_nothing_and_resends_the_same_bytes():
    with two_replicas() as (a, b):
        body = b'[{"payload_id":"p-1"}]'
        async def steps(c, bal):
            a.stop()  # replica A dies
            replies = [(await c.post("/v1/ingest", content=body)).json() for _ in range(6)]
            return replies, bal.status()

        replies, status = run(lb.create_proxy([a.url, b.url]), steps)
        assert all(r["replica"] == "B" and r["sha256"] == hashlib.sha256(body).hexdigest() for r in replies)  # every request answered, bytes intact
        assert len(b.seen) == 6 and a.seen == []  # B received each exactly once; nothing was half-delivered to A
        by_url = {u["url"]: u for u in status["upstreams"]}
        assert by_url[a.url]["healthy"] is False and by_url[b.url]["healthy"] is True
        assert status["failovers"] >= 1


def test_a_recovered_replica_is_brought_back():
    with two_replicas() as (a, b):
        async def steps(c, bal):
            a.stop()
            await c.get("/echo")  # notices A is down
            assert {u.url: u.healthy for u in bal.upstreams}[a.url] is False
            a.__init__("A", port=a.port)  # same address, fresh server
            a.start()
            await bal.check_health()
            assert {u.url: u.healthy for u in bal.upstreams}[a.url] is True
            return {(await c.get("/echo")).json()["replica"] for _ in range(6)}

        assert run(lb.create_proxy([a.url, b.url]), steps) == {"A", "B"}


def test_all_replicas_down_returns_a_fast_502_not_a_hang():
    a, b = Replica("A").start(), Replica("B").start()
    a.stop(); b.stop()
    async def steps(c, bal):
        t0 = time.time()
        r = await c.post("/v1/ingest", content=b"[]")
        return r.status_code, r.json(), r.headers.get("retry-after"), time.time() - t0

    status, body, retry_after, took = run(lb.create_proxy([a.url, b.url]), steps)
    assert status == 502 and "no replica" in body["detail"] and retry_after == "2" and took < 5


def test_a_503_is_retried_elsewhere_but_a_401_is_passed_through():
    with two_replicas() as (a, b):
        async def steps(c, bal):
            unavailable = {(await c.get("/unavailable")).status_code for _ in range(4)}  # both replicas say 503
            denied = [await c.get("/denied") for _ in range(4)]
            return unavailable, denied

        unavailable, denied = run(lb.create_proxy([a.url, b.url]), steps)
        assert unavailable == {503}  # the last replica's 503 is returned once everyone has been tried
        assert all(r.status_code == 401 for r in denied)
        assert len(a.seen) + len(b.seen) == 4  # an application error is never retried on another replica


def test_streamed_responses_pass_through():
    with two_replicas() as (a, b):
        async def steps(c, bal):
            r = await c.get("/stream")
            return r.headers["content-type"], r.text

        ctype, text = run(lb.create_proxy([a.url]), steps)
        assert ctype.startswith("text/event-stream") and text == "chunk0;chunk1;chunk2;"


def test_status_page_is_local_only():
    with two_replicas() as (a, b):
        app = lb.create_proxy([a.url, b.url])
        async def steps(c, bal):
            return (await c.get("/_lb/status")).status_code

        assert run(app, steps) == 200
        assert run(lb.create_proxy([a.url]), steps, client=("203.0.113.9", 50000)) == 403
