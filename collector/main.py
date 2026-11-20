from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .config import COLLECTOR_VERSION, Config
from .outbox import LocalStore
from .pipeline import Pipeline
from .sender import Sender


def create_app(cfg: Config | None = None, run_sender: bool = True) -> FastAPI:
    cfg = cfg or Config()
    store = LocalStore(cfg.data_dir)
    pipeline = Pipeline(cfg, store)
    sender = Sender(cfg, store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(sender.run()) if run_sender else None
        try:
            yield
        finally:
            if task:
                task.cancel()

    app = FastAPI(title="Signal Labs collector", version=COLLECTOR_VERSION, lifespan=lifespan)
    app.state.store, app.state.pipeline, app.state.sender, app.state.cfg = store, pipeline, sender, cfg

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
