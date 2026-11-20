from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Query, Request

from .auth import Auth
from .ingest import load_validator, process_batch
from .store import Store, parse_ts


def create_app(database_url: str | None = None, tenants_file: str | None = None) -> FastAPI:
    store = Store(database_url or os.getenv("DATABASE_URL", "sqlite:///./data/saas.db"))
    auth = Auth(tenants_file or os.getenv("TENANTS_FILE", "saas/config/tenants.json"))
    validator = load_validator()
    stale_after_s = int(os.getenv("STALE_AFTER_S", "60"))
    replica = os.getenv("REPLICA_ID", "1")

    app = FastAPI(title="Signal Labs SaaS", version="0.1.0")
    app.state.store = store

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "replica": replica}

    @app.post("/v1/ingest")
    async def ingest(request: Request, x_collector_key: str | None = Header(None), x_signature: str | None = Header(None)):
        body = await request.body()
        cred = auth.collector(x_collector_key, x_signature, body)
        try:
            data = json.loads(body)
            payloads = data["payloads"]
            if not isinstance(payloads, list):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, 'body must be {"payloads": [...]}')
        result = process_batch(store, validator, cred, payloads)
        result["replica"] = replica
        return result

    @app.post("/v1/heartbeat")
    async def heartbeat(request: Request, x_collector_key: str | None = Header(None), x_signature: str | None = Header(None)):
        body = await request.body()
        cred = auth.collector(x_collector_key, x_signature, body)
        try:
            data = json.loads(body)
        except ValueError:
            raise HTTPException(400, "invalid json")
        store.upsert_heartbeat(
            cred.tenant_ref, cred.collector_id, str(data.get("version"))[:16], data.get("buffer_depth"), str(data.get("config_hash"))[:64]
        )
        return {"ok": True}

    @app.get("/v1/fleet")
    def fleet(x_dashboard_token: str | None = Header(None)):
        tenant = auth.dashboard(x_dashboard_token)
        return store.fleet(tenant, stale_after_s)

    @app.get("/v1/metrics")
    def metrics(
        source: str | None = None,
        name: str | None = None,
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
        x_dashboard_token: str | None = Header(None),
    ):
        tenant = auth.dashboard(x_dashboard_token)
        try:
            start = parse_ts(from_) if from_ else None
            end = parse_ts(to) if to else None
        except ValueError:
            raise HTTPException(400, "from/to must be ISO-8601")
        return store.metrics(tenant, name, source, start, end)

    return app


def _default_app() -> FastAPI:  # created lazily so importing the module never needs a database
    return create_app()


app = _default_app() if os.getenv("SAAS_AUTOSTART", "1") == "1" else None
