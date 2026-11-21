from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .adapters import Adapters
from .config import COLLECTOR_VERSION, DEV_COLLECTOR_KEY, Config
from .enroll import EnrollmentError, ensure_enrolled
from .outbox import LocalStore, canonical
from .pipeline import Pipeline
from .push import PushGuard, otlp_to_lines, read_body
from .pull import expand
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
    cfg = ensure_enrolled(cfg or Config())  # first start with ENROLL_TOKEN set: enroll, then use the new credentials
    if cfg.credentials_source == "environment" and cfg.collector_key == DEV_COLLECTOR_KEY:
        logging.getLogger("collector").warning(
            "running on the built-in DEV credentials: enroll this collector (python -m collector.enroll) before any real use"
        )
    store = LocalStore(
        cfg.data_dir, raw_max_rows=cfg.raw_max_rows, outbox_max_pending=cfg.outbox_max_pending, max_db_bytes=cfg.max_db_bytes
    )
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

    async def retention() -> None:
        """Delete expired data on a schedule, and tell the platform if the buffer ever had to drop payloads."""
        log = logging.getLogger("collector.retention")
        while True:
            try:
                done = await asyncio.to_thread(store.apply_retention, cfg.raw_retention_s, cfg.outbox_retention_s)
                if any(done.values()):
                    log.info("retention: %s", done)
                lost = store.take_unreported_drops()
                if lost:
                    log.warning("the outbox was full: %d oldest payload(s) were dropped", lost)
                    pipeline.emit_collector_event("service_state", "warning", lost, "buffer overflow dropped payloads")
            except Exception:  # retention must never take the collector down
                log.exception("retention run failed")
            await asyncio.sleep(cfg.retention_interval_s)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        tasks = [asyncio.create_task(flusher()), asyncio.create_task(retention())]
        if host_source is not None:
            tasks.append(asyncio.create_task(host_source.run()))
        adapters = Adapters(cfg, pipeline)
        await adapters.start()
        app.state.adapters = adapters
        if run_sender:
            tasks.append(asyncio.create_task(sender.run()))
        try:
            yield
        finally:
            await adapters.stop()
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

    guard = PushGuard(cfg.ingest_token, cfg.ingest_allow)
    app.state.guard = guard

    def take(text: str) -> dict:
        results = [r for r in pipeline.process_text(expand(text)) if r["status"] != "csv_header"]
        pipeline.counters["adapter:push"] += len(results)
        summary: dict[str, int] = {}
        for r in results:
            summary[r["status"]] = summary.get(r["status"], 0) + 1
        return {"received": len(results), "summary": summary}

    @app.post("/ingest")
    async def ingest(request: Request):
        """Lines or JSON in any supported format (an array or NDJSON body is fine; gzip is accepted)."""
        guard.check(request)
        return take((await read_body(request, cfg.max_ingest_bytes)).decode("utf-8", errors="replace"))

    @app.post("/write")
    @app.post("/api/v2/write")
    async def influx_write(request: Request):
        """InfluxDB line protocol, so Telegraf's influxdb output can point straight at this collector."""
        guard.check(request)
        take((await read_body(request, cfg.max_ingest_bytes)).decode("utf-8", errors="replace"))
        return Response(status_code=204)

    @app.post("/v1/metrics")
    async def otlp_metrics(request: Request):
        """OpenTelemetry metrics as OTLP/HTTP JSON (an OpenTelemetry Collector's otlphttp exporter with encoding: json)."""
        guard.check(request)
        if "protobuf" in request.headers.get("content-type", "").lower():
            raise HTTPException(415, "OTLP protobuf is not supported; send OTLP/HTTP JSON (Content-Type: application/json)")
        try:
            doc = json.loads((await read_body(request, cfg.max_ingest_bytes)).decode("utf-8", errors="replace"))
        except ValueError:
            raise HTTPException(400, "the body is not valid JSON") from None
        lines = otlp_to_lines(doc)
        if lines:
            take("\n".join(lines))
        return {"partialSuccess": {}}

    @app.get("/local/policy")
    def local_policy():
        """Every egress field and its marking, plus what never leaves: the data policy in force."""
        return pipeline.policy.describe()

    @app.get("/local/pipeline")
    def local_pipeline():
        return {"counters": dict(pipeline.counters), "open_windows": pipeline.agg.open_windows(), "window_s": cfg.window_s}

    @app.get("/local/stages")
    def local_stages():
        """Each pipeline stage's count since start, plus what the outbox holds now (it survives restarts)."""
        adapters = getattr(app.state, "adapters", None)
        return {**pipeline.stages(), "outbox_now": store.counts(), "since_start": True, "inputs": adapters.status() if adapters else {}}

    @app.get("/local/stream")
    def local_stream():
        """Where data comes in from and the state of any stream the collector pulls (connection, lines, last error)."""
        adapters = getattr(app.state, "adapters", None)
        return {"post_ingest": True, **(adapters.status() if adapters else {"listening": {}, "following": [], "pulling": []})}

    @app.get("/local/timing")
    def local_timing():
        """The settings that decide how fast data moves. Recorded in every measurement's evidence file."""
        return {
            "profile": cfg.profile,
            "window_s": cfg.window_s,
            "grace_s": cfg.grace_s,
            "flush_interval_s": cfg.flush_interval_s,
            "send_interval_s": cfg.send_interval_s,
            "heartbeat_interval_s": cfg.heartbeat_interval_s,
            "batch_size": cfg.batch_size,
            "probe_interval_s": cfg.probe_interval_s,
            "host_interval_s": cfg.host_interval_s,
        }

    @app.get("/local/identity")
    def local_identity():
        """Who this collector is and where its credentials came from. Never returns a key or a secret."""
        return {
            "collector_id": cfg.collector_id,
            "tenant_ref": cfg.tenant_ref,
            "region": cfg.region,
            "saas_url": cfg.saas_url,
            "credentials": cfg.credentials_source,
            "enrolled_at": cfg.enrolled_at or None,
            "uses_dev_defaults": cfg.credentials_source == "environment" and cfg.collector_key == DEV_COLLECTOR_KEY,
        }

    @app.get("/local/retention")
    def local_retention():
        """What is stored, the limits, and every purge and drop so far. Data loss is counted here, never silent."""
        s = store.retention_status()
        s["policy"] = {
            "raw_records": f"deleted after {cfg.raw_retention_s} s, and trimmed to the newest {cfg.raw_max_rows} rows or {cfg.max_db_bytes} live bytes",
            "transfer_records": f"delivered or rejected payload records deleted after {cfg.outbox_retention_s} s",
            "undelivered_payloads": f"kept until delivered; if more than {cfg.outbox_max_pending} wait, the OLDEST are dropped, counted, and reported to the platform",
            "max_line_chars": cfg.max_line_chars,
            "max_request_bytes": cfg.max_ingest_bytes,
            "runs_every_s": cfg.retention_interval_s,
        }
        s["oversize_lines_dropped"] = pipeline.counters.get("oversize", 0)
        return s

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
        e["canonical_payload_utf8"] = canonical(e["payload"]).decode("utf-8")
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
            "hold": sender.hold_state(),
            **{k: v for k, v in store.pending_info().items() if k != "pending"},
        }

    def _operator_only(request: Request) -> None:
        """Changing what leaves the building needs a deliberate request from the local page itself.

        A web page open in the same browser could try to POST here (cross-site request). It cannot set a custom
        header without a preflight this server never answers, and its Host would not be the loopback name.
        """
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if not cfg.local_allow_remote and host not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(403, "hold and release answer only to the local address")
        if request.headers.get("x-requested-with") != "local-ui":
            raise HTTPException(403, "missing the X-Requested-With: local-ui header")

    @app.post("/local/hold")
    def local_hold(request: Request):
        """Stop payloads leaving. They stay in the outbox, visible in the egress panel, until released."""
        _operator_only(request)
        return sender.hold()

    @app.post("/local/release")
    def local_release(request: Request):
        _operator_only(request)
        return sender.release()

    @app.post("/local/saas-link/{state}")
    def saas_link(state: str):
        sender.link_up = state == "up"
        return {"link": "up" if sender.link_up else "down"}

    return app


try:
    app = create_app()
except EnrollmentError as exc:  # fail closed: never fall back to default credentials after a failed enrollment
    raise SystemExit(f"enrollment failed: {exc}") from None
