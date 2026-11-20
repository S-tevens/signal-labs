import asyncio
import json
import re
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from collector.config import Config
from collector.main import create_app
from collector.redact import find_spans

UI = Path(__file__).resolve().parents[1] / "ui"
SECRET_LINE = "Nov 20 09:15:01 web-1 app[311]: user alice@corp.com from 10.2.4.7 password=Hunter2! token=abc123def456"


def make(**kw):
    cfg = Config(data_dir=":memory:", host_telemetry=False, saas_url="http://127.0.0.1:1", grace_s=0, **kw)
    return create_app(cfg, run_sender=False)


def remote(app, method, path, **kw):
    """Send one request that appears to come from another machine (TestClient cannot fake the client address)."""

    async def go():
        transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://collector") as c:
            return await c.request(method, path, **kw)

    return asyncio.run(go())


def with_secret(app):
    client = TestClient(app)
    client.post("/ingest", content=SECRET_LINE)
    app.state.pipeline.flush(force=True)
    pid = app.state.store.recent_egress(1)[0]["payload_id"]
    return client, pid


# ---- spans ----
def test_spans_mark_each_sensitive_part_and_only_those():
    text = "login password=Hunter2! from 10.2.4.7 ok"
    spans = find_spans(text)
    marked = [text[s["start"]:s["end"]] for s in spans]
    assert "password=Hunter2!" in marked and "10.2.4.7" in marked
    assert text[: spans[0]["start"]] == "login "  # the harmless text is not marked


def test_overlapping_matches_merge_into_one_span():
    text = "token=10.2.4.7"  # a token rule and an ip rule overlap
    spans = find_spans(text)
    assert len(spans) == 1 and (spans[0]["start"], spans[0]["end"]) == (0, len(text))


def test_rules_filter_limits_what_is_marked():
    assert find_spans("password=x 10.2.4.7", rules=["ipv4"]) and all(s["rule"] == "ipv4" for s in find_spans("password=x 10.2.4.7", rules=["ipv4"]))
    assert find_spans("nothing secret here") == []


# ---- the lineage view: left stays, right leaves ----
def test_lineage_shows_the_secret_locally_and_not_in_the_payload():
    client, pid = with_secret(make())
    d = client.get(f"/local/lineage/{pid}").json()

    raw_text = " ".join(r["text"] for r in d["raw"])
    assert "Hunter2!" in raw_text and "alice@corp.com" in raw_text  # left: visible to the local operator
    payload_text = json.dumps(d["payload"])
    for secret in ["Hunter2!", "alice@corp.com", "10.2.4.7", "abc123def456", "web-1"]:
        assert secret not in payload_text  # right: absent

    # every sensitive value the page will highlight is a real substring of the raw text, and none is in the payload
    for r in d["raw"]:
        for s in r["spans"]:
            assert r["text"][s["start"]:s["end"]] not in payload_text
    assert {"password", "token", "email", "ipv4"} <= {s["rule"] for r in d["raw"] for s in r["spans"]}


def test_lineage_carries_markings_and_status_for_the_panel():
    client, pid = with_secret(make())
    d = client.get(f"/local/lineage/{pid}").json()
    assert d["markings"]["source_id"] == "PSEUDONYMIZED" and d["markings"]["event"] == "DERIVED_SUMMARY"
    assert d["status"] == "pending" and d["raw_total"] == len(d["raw_ids"]) >= 1


def test_unknown_payload_is_404():
    assert TestClient(make()).get("/local/lineage/not-a-real-id").status_code == 404


# ---- the local-only guard ----
def test_local_views_refuse_other_machines_but_intake_stays_open():
    app = make()
    for path in ["/local/raw", "/local/egress", "/local/ui", "/local/ui/app.js", "/local/lineage/x", "/local/policy", "/local/buffer"]:
        assert remote(app, "GET", path).status_code == 403, path
    assert remote(app, "POST", "/local/saas-link/down").status_code == 403
    assert remote(app, "POST", "/ingest", content="hello").status_code == 200  # sources may still send data
    assert remote(app, "GET", "/healthz").status_code == 200
    assert TestClient(app).get("/local/raw").status_code == 200  # this machine is fine


def test_remote_access_is_possible_only_when_explicitly_enabled():
    assert remote(make(local_allow_remote=True), "GET", "/local/raw").status_code == 200


# ---- the page itself ----
def test_ui_is_served_with_a_strict_csp_and_nosniff():
    r = TestClient(make()).get("/local/ui")
    assert r.status_code == 200 and "Local egress proof" in r.text
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert TestClient(make()).get("/local/ui/app.js").headers["content-type"].startswith("text/javascript")


def test_only_the_three_ui_files_are_reachable():
    client = TestClient(make())
    for name in ["index.html", "app.js", "style.css"]:
        assert client.get(f"/local/ui/{name}").status_code == 200
    for bad in ["../main.py", "%2e%2e/main.py", "..%2Foutbox.py", "app.js.map", "secrets.txt", "policy.yaml"]:
        assert client.get(f"/local/ui/{bad}").status_code in (404, 422), bad


def test_page_code_cannot_inject_html_from_log_text():
    """Regression guard: log lines are attacker-controlled, so the page may never turn data into markup."""
    js = (UI / "app.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", js, flags=re.S)  # ignore comments, which mention the banned names
    for banned in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout(\"", "srcdoc"]:
        assert banned not in code, f"app.js must not use {banned}"
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "no inline scripts"
    assert not re.search(r"\son[a-z]+\s*=", html), "no inline event handlers"
    assert " style=" not in html and "<style" not in html, "no inline styles"
    assert "javascript:" not in html
