import json

from collector.config import Config
from collector.outbox import LocalStore
from collector.parsers import parse_line
from collector.pipeline import Pipeline
from collector.redact import pseudonym, redact

SECRETS = [
    "Hunter2!",
    "AKIAABCDEFGHIJKLMNOP",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghijk",
    "alice@corp.com",
    "10.2.4.7",
]


def make():
    cfg = Config(data_dir=":memory:")
    store = LocalStore(":memory:")
    return Pipeline(cfg, store), store


def test_redact_scrubs_secrets():
    line = "login failed password=Hunter2! key AKIAABCDEFGHIJKLMNOP from 10.2.4.7 user alice@corp.com"
    text, rules = redact(line)
    for s in ("Hunter2!", "AKIAABCDEFGHIJKLMNOP", "10.2.4.7", "alice@corp.com"):
        assert s not in text
    assert {"password", "aws_key", "ipv4", "email"} <= set(rules)


def test_pseudonym_is_stable_and_opaque():
    a = pseudonym("10.2.4.7", "s")
    assert a == pseudonym("10.2.4.7", "s") and a != pseudonym("10.2.4.8", "s")
    assert "10.2.4.7" not in a


def test_secret_in_log_never_reaches_outbox_but_stays_local():
    pipeline, store = make()
    line = "Nov 20 09:15:01 web-1 sshd[88]: Failed password for alice@corp.com from 10.2.4.7 password=Hunter2!"
    assert pipeline.process(line)["status"] == "queued"

    egress = json.dumps(store.recent_egress())
    for secret in SECRETS:
        assert secret not in egress
    assert "web-1" not in egress  # host is pseudonymized
    assert "Hunter2!" in store.recent_raw()[0]["text"]  # raw stays local, visible to operators
    payload = store.recent_egress()[0]["payload"]
    assert payload["event"]["category"] == "auth_failure"
    assert "password" in store.recent_egress()[0]["redactions_applied"]


def test_any_format_is_parsed():
    assert parse_line('{"kind":"metric","host":"h","name":"cpu_pct","value":91}')["format"] == "json"
    assert parse_line("Nov 20 09:15:01 web-1 sshd[88]: hello")["format"] == "syslog"
    assert parse_line("ts=2026-11-20T09:15:00Z host=h metric=latency_ms value=120")["kind"] == "metric"
    assert parse_line("just some text")["format"] == "text"


def test_metric_not_on_allow_list_is_dropped():
    pipeline, store = make()
    out = pipeline.process('{"kind":"metric","host":"h","name":"internal_db_password","value":1}')
    assert out["status"] == "dropped"
    assert store.depth() == 0


def test_malformed_input_never_crashes():
    pipeline, _ = make()
    for line in ["{not json", "<<<>>>", "\x00\x01", "a=b", '{"kind":"metric","value":"abc","name":"cpu_pct"}']:
        pipeline.process(line)
