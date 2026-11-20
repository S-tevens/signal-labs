"""A small failover proxy in front of the SaaS replicas (replaces the nginx that left with Docker).

    python scripts/lb.py --listen 127.0.0.1:8080 \
        --upstream http://127.0.0.1:8000 --upstream http://127.0.0.1:8001
    # with TLS on both sides:
    python scripts/lb.py --listen 127.0.0.1:8080 --upstream https://127.0.0.1:8000 --upstream https://127.0.0.1:8001 \
        --ca data/certs/ca.pem --tls-cert data/certs/server.pem --tls-key data/certs/server.key

What it guarantees
  * Exact bytes. The request body and the headers the SaaS authenticates (X-Collector-Key, X-Signature,
    Authorization, Content-Encoding) are forwarded untouched, because the collector's HMAC covers the exact body.
  * Failover. A request goes to the next replica when the connection fails, times out, or the replica answers
    502/503/504. Real answers (200, 401, 403, 422, 500 ...) are passed through and never retried.
  * Recovery. A background check polls each replica's /healthz and brings it back when it answers again.
  * Round robin across healthy replicas.

Why retrying a POST is safe here: a retry only happens when no response arrived, so the request may have been
processed once. The SaaS de-duplicates by payload ID, so a repeat is reported as a duplicate, not stored twice.

Limits (honest): one process and one point of failure itself; a response that breaks half-way through a stream
cannot be failed over (the client reconnects); health is polled, not pushed. Not for production traffic.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import ssl
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

log = logging.getLogger("lb")

# Headers that describe one hop, not the message. Everything else is passed through unchanged.
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length"}
RETRY_STATUS = {502, 503, 504}
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ReadError, httpx.WriteError,
                     httpx.WriteTimeout, httpx.PoolTimeout, httpx.RemoteProtocolError, httpx.LocalProtocolError)


@dataclass
class Upstream:
    url: str
    healthy: bool = True
    requests: int = 0
    failures: int = 0
    last_error: str | None = None
    changed_at: float = 0.0


class Balancer:
    def __init__(self, urls: list[str], ca: str | None = None, timeout_s: float = 30.0, connect_timeout_s: float = 2.0):
        if not urls:
            raise ValueError("at least one --upstream is required")
        self.upstreams = [Upstream(u.rstrip("/")) for u in urls]
        self._next = 0
        self.failovers = 0
        self.total = 0
        verify: ssl.SSLContext | bool = True
        if any(u.url.startswith("https://") for u in self.upstreams):
            verify = ssl.create_default_context(cafile=ca or None)  # always verified; trusts only --ca when given
            verify.minimum_version = ssl.TLSVersion.TLSv1_2
        self.client = httpx.AsyncClient(verify=verify, timeout=httpx.Timeout(timeout_s, connect=connect_timeout_s), follow_redirects=False)

    # ---- choosing a replica ----
    def order(self) -> list[Upstream]:
        """Healthy replicas first, rotated for round robin; unhealthy ones last, as a final resort."""
        n = len(self.upstreams)
        start, self._next = self._next % n, (self._next + 1) % n
        rotated = self.upstreams[start:] + self.upstreams[:start]
        return [u for u in rotated if u.healthy] + [u for u in rotated if not u.healthy]

    def _set(self, up: Upstream, healthy: bool, why: str | None = None) -> None:
        if up.healthy != healthy:
            up.changed_at = time.time()
            log.warning("replica %s is now %s%s", up.url, "UP" if healthy else "DOWN", f" ({why})" if why else "")
        up.healthy = healthy
        if why:
            up.last_error = why

    # ---- forwarding ----
    async def forward(self, request: Request, body: bytes):
        """Return (upstream, streamed response), or None if every replica failed."""
        raw_path = request.scope.get("raw_path") or request.url.path.encode()
        target_tail = raw_path.decode("ascii", "replace")
        query = request.scope.get("query_string", b"").decode("ascii", "replace")
        if query:
            target_tail += "?" + query
        headers = [(k, v) for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP]
        candidates = self.order()
        for i, up in enumerate(candidates):
            last = i == len(candidates) - 1
            try:
                req = self.client.build_request(request.method, up.url + target_tail, headers=headers, content=body)
                resp = await self.client.send(req, stream=True)
            except CONNECTION_ERRORS as exc:
                up.failures += 1
                self._set(up, False, f"{type(exc).__name__}")
                self.failovers += 1
                continue
            if resp.status_code in RETRY_STATUS and not last:
                await resp.aclose()
                up.failures += 1
                self._set(up, False, f"HTTP {resp.status_code}")
                self.failovers += 1
                continue
            up.requests += 1
            self.total += 1
            self._set(up, True)
            return up, resp
        return None

    async def check_health(self) -> None:
        async def one(up: Upstream) -> None:
            try:
                r = await self.client.get(up.url + "/healthz", timeout=2.0)
                self._set(up, r.status_code == 200, None if r.status_code == 200 else f"healthz HTTP {r.status_code}")
            except Exception as exc:  # any failure means "not healthy right now"
                self._set(up, False, type(exc).__name__)

        await asyncio.gather(*(one(u) for u in self.upstreams))

    def status(self) -> dict:
        return {
            "upstreams": [
                {"url": u.url, "healthy": u.healthy, "requests": u.requests, "failures": u.failures, "last_error": u.last_error}
                for u in self.upstreams
            ],
            "total_requests": self.total,
            "failovers": self.failovers,
        }


def create_proxy(urls: list[str], ca: str | None = None, health_interval_s: float = 2.0) -> FastAPI:
    balancer = Balancer(urls, ca=ca)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def loop() -> None:
            while True:
                await balancer.check_health()
                await asyncio.sleep(health_interval_s)

        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            await balancer.client.aclose()

    app = FastAPI(title="Signal Labs failover proxy", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.balancer = balancer

    @app.get("/_lb/status")
    async def status(request: Request):
        if (request.client.host if request.client else "") not in LOCAL_HOSTS:
            return JSONResponse({"detail": "status is only available from this machine"}, status_code=403)
        return balancer.status()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def proxy(request: Request, path: str):
        body = await request.body()  # the exact bytes the client signed
        result = await balancer.forward(request, body)
        if result is None:
            return JSONResponse(
                {"detail": "no replica available", "upstreams": [u.url for u in balancer.upstreams]},
                status_code=502,
                headers={"Retry-After": "2"},
            )
        _, resp = result
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}
        # Raw bytes in, raw bytes out: no decoding, so content-encoding and signatures stay intact.
        return StreamingResponse(resp.aiter_raw(), status_code=resp.status_code, headers=out_headers, background=BackgroundTask(resp.aclose))

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", default="127.0.0.1:8080", help="host:port to listen on")
    ap.add_argument("--upstream", action="append", required=True, help="replica base URL (repeat for each replica)")
    ap.add_argument("--ca", default=None, help="CA file that signed the replicas' certificates (https upstreams)")
    ap.add_argument("--tls-cert", default=None, help="serve HTTPS with this certificate")
    ap.add_argument("--tls-key", default=None)
    ap.add_argument("--health-interval", type=float, default=2.0)
    args = ap.parse_args()
    host, _, port = args.listen.rpartition(":")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        create_proxy(args.upstream, ca=args.ca, health_interval_s=args.health_interval),
        host=host or "127.0.0.1", port=int(port), ssl_certfile=args.tls_cert, ssl_keyfile=args.tls_key,
        log_level="warning", access_log=False,
    )


if __name__ == "__main__":
    main()
