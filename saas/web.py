"""One public address for a single-host deployment (Render): the platform API and the built dashboard together.

  /api/v1/...   the dashboard's calls (same origin, so no CORS). Collector routes are refused here.
  /v1/ingest, /v1/heartbeat, /healthz   used directly by customer collectors and the host's health check
  everything else   the built dashboard (dashboard/dist), with index.html for unknown paths
"""
import os
import re
from pathlib import Path

from starlette.responses import PlainTextResponse
from starlette.staticfiles import StaticFiles

from .main import app as api

DIST = Path(os.getenv("DASHBOARD_DIST") or Path(__file__).resolve().parents[1] / "dashboard" / "dist")
DIRECT = {"/v1/ingest", "/v1/heartbeat", "/healthz"}
BLOCKED = re.compile(r"^/v1/(ingest|heartbeat|enroll|enrollment-tokens)(/|$)")
static = StaticFiles(directory=DIST, html=True, check_dir=False)


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        return await api(scope, receive, send)
    path = scope.get("path", "/")
    if path.startswith("/api/"):
        sub = path[4:]
        if BLOCKED.match(sub):
            return await PlainTextResponse("not available on the public address", status_code=403)(scope, receive, send)
        return await api(dict(scope, path=sub, raw_path=sub.encode()), receive, send)
    if path in DIRECT:
        return await api(scope, receive, send)
    if scope["type"] == "http":
        name = path.rsplit("/", 1)[-1]
        if "." not in name and path != "/" and not (DIST / path.lstrip("/")).is_file():
            scope = dict(scope, path="/", raw_path=b"/")
    return await static(scope, receive, send)
