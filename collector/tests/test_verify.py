"""The proof tools' logic (E19): comparison, canary detection in every encoded form, and honest verdicts."""
import base64
import importlib.util
import json
import sys
import urllib.parse
from pathlib import Path

from collector.outbox import digest_of

_spec = importlib.util.spec_from_file_location("verify", Path(__file__).resolve().parents[2] / "simulator" / "verify.py")
verify = importlib.util.module_from_spec(_spec)
sys.modules["verify"] = verify
_spec.loader.exec_module(verify)

P = {"payload_id": "p1", "collector_id": "c1", "event_ts_utc": "2026-11-20T10:00:05Z", "metric": {"name": "cpu", "value": 41.0, "unit": "%"}}


def row(payload=P, status="sent"):
    return {"payload_id": payload["payload_id"], "payload": payload, "status": status, "digest": digest_of(payload)}


def stored_copy(payload=P):
    return {**payload, "event_ts_utc": "2026-11-20T10:00:05.000000Z"}  # the platform's microsecond form


def test_identical_payloads_match_even_though_the_platform_widens_the_timestamp():
    r = verify.match_summary([row()], {"p1": stored_copy()})
    assert r["verdict"] == "PASS" and r["identical_at_platform"] == 1


def test_a_missing_payload_fails():
    r = verify.match_summary([row()], {"p1": None})
    assert r["verdict"] == "FAIL" and r["missing_at_platform"] == 1


def test_a_changed_field_fails_and_names_the_field():
    changed = stored_copy({**P, "metric": {"name": "cpu", "value": 99.0, "unit": "%"}})
    r = verify.match_summary([row()], {"p1": changed})
    assert r["verdict"] == "FAIL" and r["different_examples"][0]["fields"] == ["metric"]


def test_an_extra_field_stored_at_the_platform_fails():
    r = verify.match_summary([row()], {"p1": {**stored_copy(), "note": "x"}})
    assert r["verdict"] == "FAIL" and r["different_examples"][0]["fields"] == ["note"]


def test_a_platform_payload_the_collector_never_sent_fails():
    r = verify.match_summary([row()], {"p1": stored_copy()}, platform_ids_for_collector=["p1", "ghost"])
    assert r["verdict"] == "FAIL" and r["at_platform_but_never_sent_by_collector"] == 1


def test_an_egress_log_that_no_longer_matches_its_digest_fails():
    bad = row()
    bad["digest"] = "0" * 64
    assert verify.match_summary([bad], {"p1": stored_copy()})["verdict"] == "FAIL"


def test_nothing_sent_is_incomplete_not_a_pass():
    assert verify.match_summary([row(status="pending")], {})["verdict"] == "INCOMPLETE"


def test_unsent_payloads_are_reported_but_do_not_fail_the_check():
    r = verify.match_summary([row(), row({**P, "payload_id": "p2"}, status="pending")], {"p1": stored_copy()})
    assert r["verdict"] == "PASS" and r["not_sent_by_status"] == {"pending": 1}


def test_canaries_are_unique_per_run_and_cover_the_secret_kinds():
    a, b = verify.make_canaries("aaaa1111"), verify.make_canaries("bbbb2222")
    assert not set(a.values()) & set(b.values())
    assert {"password", "api_key", "jwt", "email", "aws_key", "username", "hostname", "free_text"} <= set(a)
    assert a["aws_key"].startswith("AKIA") and len(a["aws_key"]) == 20


def test_the_scanner_finds_every_canary_in_every_encoded_form():
    c = verify.make_canaries("c0ffee12")
    for label, value in c.items():
        forms = [value, value.lower(), json.dumps({"k": value}), urllib.parse.quote(value, safe=""),
                 base64.b64encode(value.encode()).decode(), base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")]
        for text in forms:
            assert any(h["canary"] == label for h in verify.scan_text("x " + text + " y", c)), (label, text)


def test_clean_text_has_no_hits_and_a_lookalike_is_not_a_hit():
    c = verify.make_canaries("c0ffee12")
    assert verify.scan_text(json.dumps(P), c) == []
    assert verify.scan_text("canary-host-c0ffee13", c) == []


def test_canary_lines_contain_every_canary_value():
    c = verify.make_canaries("c0ffee12")
    text = "\n".join(verify.canary_lines("c0ffee12", c))
    for label, value in c.items():
        assert value in text, label


def test_older_payloads_the_collector_did_send_are_not_reported_as_unexplained():
    old = {**P, "payload_id": "old"}
    r = verify.match_summary([row()], {"p1": stored_copy()}, platform_ids_for_collector=["p1", "old"], known_ids={"p1", "old"})
    assert r["verdict"] == "PASS" and r["at_platform_but_never_sent_by_collector"] == 0
    assert verify.match_summary([row()], {"p1": stored_copy()}, platform_ids_for_collector=["p1", "ghost"], known_ids={"p1", "old"})["verdict"] == "FAIL"
