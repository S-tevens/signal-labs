"""The AI engine: what the model may see, how it fails, and that the key never leaks."""
import json

import httpx

from saas import llm

KEY = "AQ.test-key-0123456789abcdefghijklmnopqrstuv"

INCIDENT = {
    "severity": "critical", "alert_count": 3, "first_ts": "2026-11-20T10:00:00Z", "last_ts": "2026-11-20T10:00:09Z",
    "source_id": "src_abcdef12", "collector_id": "col-blr-01",
    "signals": [{"signal": "cpu", "value": 97.0, "unit": "%", "method": "threshold fallback", "severity": "critical", "why": "cpu breached the critical threshold",
                 "payload_id": "11111111-1111-1111-1111-111111111111", "message": "raw log text that must never travel", "hostname": "srv-17.corp"}],
    "recommendation": {"action": "Check recent deploys", "likely_cause": "possible runaway process", "confidence": "low", "internal_note": "drop me"},
}


def engine(handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return llm.Engine(key=kw.pop("key", KEY), client=client, **kw)


def ok(request):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "What happened: CPU hit 97%.", "thought": False}]}}]})


def test_the_model_sees_only_allow_listed_metadata():
    facts = llm.build_facts(INCIDENT)
    blob = json.dumps(facts)
    for forbidden in ("src_abcdef12", "col-blr-01", "11111111-1111", "raw log text", "srv-17", "internal_note", "message", "hostname"):
        assert forbidden not in blob, forbidden
    assert facts["signals"][0]["signal"] == "cpu" and facts["signals"][0]["value"] == 97.0
    assert facts["rule_based_suggestion"]["action"] == "Check recent deploys"


def test_a_summary_is_returned_with_its_basis_and_the_key_travels_only_in_a_header():
    seen = {}

    def handler(request):
        seen["url"], seen["key"], seen["body"] = str(request.url), request.headers.get("x-goog-api-key"), request.content.decode()
        return ok(request)

    r = engine(handler).explain(INCIDENT)
    assert r["available"] and r["text"].startswith("What happened") and "not proof of a root cause" in r["basis"] and r["cached"] is False
    assert seen["key"] == KEY and KEY not in seen["url"] and KEY not in seen["body"]
    assert "src_abcdef12" not in seen["body"] and "raw log text" not in seen["body"]


def test_results_are_cached_until_the_evidence_changes():
    calls = []
    e = engine(lambda req: (calls.append(1), ok(req))[1])
    e.explain(INCIDENT)
    assert e.explain(INCIDENT)["cached"] is True and len(calls) == 1
    changed = {**INCIDENT, "signals": [{**INCIDENT["signals"][0], "value": 99.0}]}
    e.explain(changed)
    assert len(calls) == 2


def test_no_key_means_no_call_and_a_clear_reason(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "KEY_FILE", tmp_path / "missing.key")
    calls = []
    e = llm.Engine(key=None, client=httpx.Client(transport=httpx.MockTransport(lambda r: (calls.append(1), ok(r))[1])))
    r = e.explain(INCIDENT)
    assert r["available"] is False and "key" in r["reason"] and not calls and e.status()["available"] is False


def test_failures_degrade_without_raising_or_leaking_the_key():
    for handler in (lambda r: httpx.Response(500, text="boom " + KEY), lambda r: httpx.Response(200, json={"candidates": []}),
                    lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("slow " + KEY))):
        r = engine(handler).explain(INCIDENT)
        assert r["available"] is False and KEY not in json.dumps(r)


def test_an_incident_without_signals_is_not_sent():
    calls = []
    r = engine(lambda req: (calls.append(1), ok(req))[1]).explain({"severity": "info", "signals": []})
    assert r["available"] is False and not calls


def test_the_rate_limit_stops_a_flood_of_calls():
    e = engine(ok, max_per_minute=2)
    for i in range(2):
        assert e.explain({**INCIDENT, "alert_count": i})["available"]
    assert e.explain({**INCIDENT, "alert_count": 99})["available"] is False


def test_the_key_can_come_from_the_environment_or_a_file(monkeypatch, tmp_path):
    f = tmp_path / "k"
    f.write_text("  from-file \n", encoding="utf-8")
    monkeypatch.setattr(llm, "KEY_FILE", f)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm.load_key() == "from-file"
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert llm.load_key() == "from-env"


def test_an_overloaded_model_falls_back_to_the_next_one():
    tried = []

    def handler(request):
        model = str(request.url).split("/models/")[1].split(":")[0]
        tried.append(model)
        return httpx.Response(503, text="busy") if len(tried) == 1 else ok(request)

    r = engine(handler).explain(INCIDENT)
    assert r["available"] and len(tried) == 2 and tried[0] != tried[1] and r["model"] == tried[1]


def test_a_bad_request_does_not_burn_through_the_fallbacks():
    tried = []
    r = engine(lambda req: (tried.append(1), httpx.Response(400, text="bad"))[1]).explain(INCIDENT)
    assert r["available"] is False and len(tried) == 1 and "400" in r["reason"]
