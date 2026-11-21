"""The payload trace's pure parts (E27): masking, the leak check and the incident summary."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("trace_tool", Path(__file__).resolve().parents[2] / "simulator" / "trace.py")
trace = importlib.util.module_from_spec(_spec)
sys.modules["trace_tool"] = trace
_spec.loader.exec_module(trace)

TEXT = "login password=Hunter2! from 10.2.4.7 ok"
SPANS = [{"start": 6, "end": 23, "rule": "password"}, {"start": 29, "end": 37, "rule": "ipv4"}]


def test_masking_hides_every_sensitive_span_and_keeps_the_rest():
    out = trace.mask(TEXT, SPANS)
    assert "Hunter2" not in out and "10.2.4.7" not in out and out.startswith("login [password:17 chars]") and out.endswith(" ok")
    assert trace.mask(TEXT, SPANS, reveal=True) == TEXT


def test_overlapping_spans_are_merged_not_double_masked():
    out = trace.mask("abcdefghij", [{"start": 1, "end": 5, "rule": "a"}, {"start": 3, "end": 8, "rule": "b"}])
    assert out == "a[a+b:7 chars]ij"


def test_the_leak_check_finds_a_value_in_the_payload_and_ignores_clean_ones():
    raw = [{"text": TEXT, "spans": SPANS}]
    assert trace.leaked({"summary": "x"}, raw) == []
    assert trace.leaked({"summary": "saw password=Hunter2! here"}, raw) == ["password"]


def test_received_hop_reports_missing_and_differences():
    payload = {"payload_id": "p", "event_ts_utc": "2026-11-20T10:00:05Z", "metric": {"name": "cpu_pct", "value": 1.0, "unit": "%"}}
    assert trace.hop_received(payload, None)[0] is False
    ok, _ = trace.hop_received(payload, {**payload, "event_ts_utc": "2026-11-20T10:00:05.000000Z"})
    assert ok
    assert trace.hop_received(payload, {**payload, "metric": {"name": "cpu_pct", "value": 2.0, "unit": "%"}})[0] is False


def test_incident_summary_keeps_only_this_payloads_signals():
    inc = {"id": "i1", "properties": {"severity": "critical", "source_id": "s", "signals": [
        {"payload_id": "p1", "signal": "failed_login", "value": 30, "why": "w", "method": "local event summary"},
        {"payload_id": "p2", "signal": "cpu_pct", "value": 99}],
        "recommendation": {"action": "Review", "confidence": "low", "nested": {"x": 1}}}}
    s = trace.summarize_incident(inc, "p1")
    assert s["signals_in_incident"] == 2 and [x["signal"] for x in s["signals_from_this_payload"]] == ["failed_login"]
    assert s["recommendation"] == {"action": "Review", "confidence": "low"}


def test_outgoing_proof_requires_sent_status_and_matches_payload_digest():
    payload={'payload_id':'p','metric':{'name':'cpu_pct','value':20,'unit':'%'}}
    lineage={'payload':payload,'digest':trace.verify.digest_of(payload),'raw':[],'status':'pending','sent_at':None}
    assert not trace.hop_outgoing(lineage)[0]
    lineage['status']='sent'
    assert trace.hop_outgoing(lineage)[0]
    assert any('not the full batched HTTP request' in line for line in trace.hop_outgoing(lineage)[1])


def test_show_secrets_never_writes_recognized_spans_to_evidence(tmp_path, monkeypatch, capsys):
    payload={'payload_id':'p','tenant_ref':'t','collector_id':'c','source_id':'s'}
    lineage={'payload_id':'p','payload':payload,'digest':trace.verify.digest_of(payload),'status':'sent','sent_at':1,
             'raw':[{'id':1,'received_at':1,'text':TEXT,'spans':SPANS}],'raw_total':1}
    monkeypatch.setattr(trace,'fetch_lineage',lambda _:lineage)
    monkeypatch.setattr(trace.verify,'platform_observation',lambda _:payload)
    monkeypatch.setattr(trace,'hop_incident',lambda *_, **__:(True,['test incident']))
    monkeypatch.setattr(trace.verify,'ROOT',tmp_path)
    monkeypatch.setattr(trace,'EVIDENCE',tmp_path/'evidence')
    monkeypatch.setattr(sys,'argv',['trace.py','p','--show-secrets'])
    assert trace.main()==0
    assert 'Hunter2!' in capsys.readouterr().out
    evidence=next((tmp_path/'evidence').glob('trace-*.md')).read_text()
    assert 'Hunter2!' not in evidence and '10.2.4.7' not in evidence
    assert 'login ' not in evidence and 'raw text omitted from evidence' in evidence


def test_hold_demo_releases_on_interrupted_input(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(trace.uuid, 'uuid4', lambda: SimpleNamespace(hex='abcdef012345'))
    calls=[]
    def call(url, *args, **kwargs):
        calls.append(url)
        if url.endswith('/local/buffer'): return 200, {'hold':{'held':False}}
        if url.endswith('/local/hold') or url.endswith('/local/release'): return 200, {}
        if '/v1/objects/observation/' in url: return 404, {}
        raise AssertionError(url)
    monkeypatch.setattr(trace.sc, '_call', call)
    monkeypatch.setattr(trace.sc, 'collector_send', lambda _:None)
    monkeypatch.setattr(trace.time, 'sleep', lambda _:None)
    egress=iter([[], [{'payload_id':'p','payload':{'event':{} }}]])
    monkeypatch.setattr(trace.verify, 'collector_egress', lambda:next(egress))
    monkeypatch.setattr(trace, 'fetch_lineage', lambda _:{'status':'pending','payload':{},'raw':[{'text':'Tr4ce!abcdefPw','spans':[]}]})
    monkeypatch.setattr('builtins.input',lambda: (_ for _ in ()).throw(EOFError()))
    import pytest
    with pytest.raises(RuntimeError, match='interactive input ended'):
        trace.demo_payload(hold=True)
    assert any(url.endswith('/local/release') for url in calls)


def test_hold_demo_preserves_an_existing_hold(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(trace.uuid, 'uuid4', lambda: SimpleNamespace(hex='abcdef012345'))
    monkeypatch.setattr(trace.verify, 'collector_egress', lambda:[])
    calls=[]
    def call(url, *args, **kwargs):
        calls.append(url)
        return 200, {'hold':{'held':True}}
    monkeypatch.setattr(trace.sc, '_call', call)
    import pytest
    with pytest.raises(RuntimeError, match='already held'):
        trace.demo_payload(hold=True)
    assert not any(url.endswith('/local/release') for url in calls)


def test_linked_incident_needs_actionable_recommendation(monkeypatch):
    def call(url, **kwargs):
        if '/lineage/payload/' in url: return 200, {'incidents':[{'incident_id':'i','signals':[]}]}
        return 200, {'id':'i','properties':{'signals':[{'payload_id':'p','signal':'cpu'}]}}
    monkeypatch.setattr(trace.sc,'_call',call)
    assert trace.hop_incident('p',True)[0] is False
