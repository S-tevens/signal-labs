from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .config import COLLECTOR_VERSION, Config
from .outbox import LocalStore
from .pipeline import Pipeline
from .redact import find_spans
from .sender import Sender

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_UI_DIR = Path(__file__).resolve().parent / "ui"
_UI_FILES = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}
# The page renders log text that an attacker may control. Scripts and styles only from this origin, no inline
# anything, no framing, and the page may only talk to this collector.
_UI_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _ui_file(name: str) -> Response:
    return Response((_UI_DIR / name).read_bytes(), media_type=_UI_FILES[name], headers=_UI_HEADERS)


def create_app(cfg: Config | None = None, run_sender: bool = True) -> FastAPI:
    cfg = cfg or Config()
    store = LocalStore(cfg.data_dir)
    pipeline = Pipeline(cfg, store)
    sender = Sender(cfg, store)

    host_source = None
    if cfg.host_telemetry:
        try:
            from .sources.host import HostSource

            host_source = HostSource(cfg, pipeline)
        except ImportError:
            logging.getLogger("collector").warning("psutil is not installed: host telemetry is disabled")

    async def flusher() -> None:
        # Close finished windows on a timer, so a quiet source still reports.
        while True:
            pipeline.flush()
            await asyncio.sleep(cfg.flush_interval_s)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        tasks = [asyncio.create_task(flusher())]
        if host_source is not None:
            tasks.append(asyncio.create_task(host_source.run()))
        if run_sender:
            tasks.append(asyncio.create_task(sender.run()))
        try:
            yield
        finally:
            pipeline.flush(force=True)  # do not lose the open windows on shutdown
            for task in tasks:
                task.cancel()

    app = FastAPI(title="Signal Labs collector", version=COLLECTOR_VERSION, lifespan=lifespan)
    app.state.store, app.state.pipeline, app.state.sender, app.state.cfg = store, pipeline, sender, cfg

    @app.middleware("http")
    async def local_views_are_local(request: Request, call_next):
        """Raw records and secrets are visible under /local/*, so only this machine may ask for them."""
        if request.url.path.startswith("/local") and not cfg.local_allow_remote:
            host = request.client.host if request.client else ""
            if host not in _LOCAL_HOSTS:
                return JSONResponse({"detail": "the local views answer only requests from this machine"}, status_code=403)
        return await call_next(request)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "collector_id": cfg.collector_id, "version": COLLECTOR_VERSION}

    @app.post("/ingest")
    async def ingest(request: Request):
        text = (await request.body()).decode("utf-8", errors="replace")
        results = [pipeline.process(line) for line in text.splitlines() if line.strip()]
        summary: dict[str, int] = {}
        for r in results:
            summary[r["status"]] = summary.get(r["status"], 0) + 1
        return {"received": len(results), "summary": summary}

    @app.get("/local/policy")
    def local_policy():
        """Every egress field and its marking, plus what never leaves: the data policy in force."""
        return pipeline.policy.describe()

    @app.get("/local/pipeline")
    def local_pipeline():
        return {"counters": dict(pipeline.counters), "open_windows": pipeline.agg.open_windows(), "window_s": cfg.window_s}

    @app.get("/local/host")
    def local_host():
        """What this collector is measuring on its own machine (local view: real host and target names)."""
        if host_source is None:
            return {"enabled": False}
        return {"enabled": True, **host_source.status()}

    @app.get("/local/lineage/{payload_id}")
    def local_lineage(payload_id: str, max_raw: int = 20):
        """One payload and the raw records behind it: what stayed (left) and what left (right).

        Raw text is returned unredacted because this is the local operator's view; `spans` say which parts are
        sensitive so the page can highlight them. This never goes to the SaaS.
        """
        e = store.egress_one(payload_id)
        if e is None:
            raise HTTPException(404, "unknown payload id")
        raws = store.raw_by_ids(e["raw_ids"][: max(1, min(max_raw, 100))])
        rules = pipeline.policy.redaction_rules
        e["raw"] = [
            {"id": r["id"], "received_at": r["received_at"], "text": r["text"][:4000], "spans": find_spans(r["text"][:4000], rules)}
            for r in raws
        ]
        e["raw_total"] = len(e["raw_ids"])
        e["markings"] = {k: pipeline.policy.fields[k]["classification"] for k in e["payload"] if k in pipeline.policy.fields}
        return e

    @app.get("/local/ui")
    @app.get("/local/ui/")
    def local_ui_index():
        return _ui_file("index.html")

    @app.get("/local/ui/{name}")
    def local_ui_asset(name: str):
        if name not in _UI_FILES:  # an explicit whitelist: nothing else on disk is reachable from here
            raise HTTPException(404, "not found")
        return _ui_file(name)

    @app.get("/local/raw")
    def local_raw(limit: int = 50):
        return store.recent_raw(limit)

    @app.get("/local/egress")
    def local_egress(limit: int = 50):
        return store.recent_egress(limit)

    @app.get("/local/buffer")
    def local_buffer():
        return {
            "link": "up" if sender.link_up else "down",
            "transport": sender.transport,
            "pending": store.depth(),
            "counts": store.counts(),
            "last_send_utc": sender.last_send_utc,
            "last_error": sender.last_error,
        }

    @app.post("/local/saas-link/{state}")
    def saas_link(state: str):
        sender.link_up = state == "up"
        return {"link": "up" if sender.link_up else "down"}

    return app


app = create_app()
