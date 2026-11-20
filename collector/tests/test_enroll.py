import json
import os
import secrets
import socket
import subprocess
import threading
import time
from contextlib import contextmanager

import pytest

pytest.importorskip("cryptography")  # the TLS fixtures need it
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from collector import credentials  # noqa: E402
from collector.config import DEV_COLLECTOR_KEY, Config  # noqa: E402
from collector.devcerts import generate  # noqa: E402
from collector.enroll import EnrollmentError, enroll, enroll_and_save, ensure_enrolled, main  # noqa: E402
from collector.main import create_app  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Platform:
    """A stand-in for the SaaS /v1/enroll endpoint, served over real HTTPS (or plain HTTP)."""

    def __init__(self, certs=None, tenant="t-acme", collector="col-new-01"):
        self.tenant, self.collector, self.certs = tenant, collector, certs
        self.tokens: dict[str, bool] = {}  # token -> used
        self.mode = "ok"
        self.issued: list[dict] = []
        self.port = free_port()
        self.scheme = "https" if certs else "http"
        app = FastAPI()

        @app.post("/v1/enroll")
        async def enroll_endpoint(request: Request):
            body = await request.json()
            token = body.get("token")
            if self.mode == "500":
                return JSONResponse({"detail": "boom"}, status_code=500)
            if self.mode == "422":
                return JSONResponse({"detail": "bad"}, status_code=422)
            if token not in self.tokens or self.tokens[token] or body.get("tenant_ref") != self.tenant:
                return JSONResponse({"detail": "Invalid or expired enrollment token"}, status_code=401)
            self.tokens[token] = True
            key, secret = f"{self.tenant}.{secrets.token_urlsafe(24)}", secrets.token_urlsafe(32)
            self.issued.append({"key": key, "secret": secret})
            reply = {"collector_id": self.collector, "tenant_ref": self.tenant, "region": "in", "collector_key": key, "collector_secret": secret}
            if self.mode == "missing":
                del reply["collector_secret"]
            if self.mode == "wrong_tenant":
                reply["tenant_ref"] = "t-someone-else"
            return reply

        kw = {"ssl_keyfile": str(certs["server.key"]), "ssl_certfile": str(certs["server.pem"])} if certs else {}
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error", **kw))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self):
        return f"{self.scheme}://127.0.0.1:{self.port}"

    def new_token(self):
        token = secrets.token_urlsafe(32)
        self.tokens[token] = False
        return token

    def __enter__(self):
        self.thread.start()
        end = time.time() + 10
        while not self.server.started and time.time() < end:
            time.sleep(0.05)
        assert self.server.started
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("enroll-certs"))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("COLLECTOR_KEY", "PSEUDO_SECRET", "SAAS_URL", "ENROLL_TOKEN", "ENROLL_TENANT", "ENROLL_ALLOW_HTTP", "SAAS_CA_FILE", "DATA_DIR"):
        monkeypatch.delenv(name, raising=False)


# ---- the happy path ----
def test_enrollment_saves_credentials_and_config_uses_them(certs, tmp_path):
    with Platform(certs) as p:
        token = p.new_token()
        path, restricted, info = enroll_and_save(tmp_path, p.url, "t-acme", token, ca_file=str(certs["ca.pem"]))
        assert path.name == "credentials.json" and restricted
        assert info["collector_id"] == "col-new-01" and "collector_secret" not in info and "pseudo_secret" not in info

        saved = json.loads(path.read_text())
        assert saved["collector_key"] == p.issued[0]["key"] and saved["collector_secret"] == p.issued[0]["secret"]
        assert len(saved["pseudo_secret"]) == 64  # created locally; the platform never sees it

        cfg = Config(data_dir=tmp_path)
        assert (cfg.collector_id, cfg.tenant_ref, cfg.region) == ("col-new-01", "t-acme", "in")
        assert cfg.collector_key == saved["collector_key"] and cfg.collector_secret == saved["collector_secret"]
        assert cfg.pseudo_secret == saved["pseudo_secret"] != Config(data_dir=":memory:").pseudo_secret  # not the dev default
        assert cfg.saas_url == p.url and cfg.credentials_source == "enrolled"


def test_an_explicit_environment_key_still_wins(certs, tmp_path, monkeypatch):
    with Platform(certs) as p:
        enroll_and_save(tmp_path, p.url, "t-acme", p.new_token(), ca_file=str(certs["ca.pem"]))
    monkeypatch.setenv("COLLECTOR_KEY", "operator-override")
    cfg = Config(data_dir=tmp_path)
    assert cfg.collector_key == "operator-override" and cfg.credentials_source == "environment"


# ---- the token is single use, and failures leave nothing behind ----
def test_the_token_is_spent_and_a_second_use_changes_nothing(certs, tmp_path):
    with Platform(certs) as p:
        token = p.new_token()
        enroll_and_save(tmp_path / "a", p.url, "t-acme", token, ca_file=str(certs["ca.pem"]))
        with pytest.raises(EnrollmentError, match="invalid, expired or already used"):
            enroll_and_save(tmp_path / "b", p.url, "t-acme", token, ca_file=str(certs["ca.pem"]))
        assert not credentials.exists(tmp_path / "b")


def test_wrong_ca_is_rejected_and_nothing_is_saved_and_the_token_is_not_leaked(certs, tmp_path):
    other = generate(tmp_path / "other-ca")  # a valid CA, but not the one that signed the platform
    with Platform(certs) as p:
        token = p.new_token()
        with pytest.raises(EnrollmentError) as err:
            enroll_and_save(tmp_path / "e", p.url, "t-acme", token, ca_file=str(other["ca.pem"]))
        assert token not in str(err.value) and "could not reach" in str(err.value)
        assert not credentials.exists(tmp_path / "e")
        assert p.tokens[token] is False  # the request never even reached the platform


def test_plain_http_is_refused_by_default(tmp_path):
    with Platform() as p:  # an http:// platform
        token = p.new_token()
        with pytest.raises(EnrollmentError, match="plain HTTP") as err:
            enroll(p.url, "t-acme", token)
        assert token not in str(err.value)
        assert p.tokens[token] is False  # refused before anything was sent
        creds = enroll(p.url, "t-acme", token, allow_http=True)  # the explicit dev override
        assert creds["collector_id"] == "col-new-01"


def test_bad_platform_replies_are_handled_and_never_saved(certs, tmp_path):
    with Platform(certs) as p:
        for mode, text in [("500", "HTTP 500"), ("422", "rejected the request"), ("missing", "valid enrollment response"), ("wrong_tenant", "does not match")]:
            p.mode = mode
            with pytest.raises(EnrollmentError, match=text):
                enroll_and_save(tmp_path / mode, p.url, "t-acme", p.new_token(), ca_file=str(certs["ca.pem"]))
            assert not credentials.exists(tmp_path / mode), mode


def test_bad_inputs_are_refused_before_any_request(tmp_path):
    for tenant, token in [("not-a-tenant", "x" * 40), ("t-acme", ""), ("t-acme", "short")]:
        with pytest.raises(EnrollmentError):
            enroll("https://127.0.0.1:1", tenant, token)


# ---- re-enrollment ----
def test_enrolling_again_needs_force_and_keeps_the_pseudonym_secret(certs, tmp_path):
    with Platform(certs) as p:
        ca = str(certs["ca.pem"])
        enroll_and_save(tmp_path, p.url, "t-acme", p.new_token(), ca_file=ca)
        first = credentials.load(tmp_path)
        with pytest.raises(EnrollmentError, match="already enrolled"):
            enroll_and_save(tmp_path, p.url, "t-acme", p.new_token(), ca_file=ca)
        enroll_and_save(tmp_path, p.url, "t-acme", p.new_token(), ca_file=ca, force=True)
        second = credentials.load(tmp_path)
        assert second["collector_key"] != first["collector_key"]  # new credentials
        assert second["pseudo_secret"] == first["pseudo_secret"]  # but source ids stay stable


# ---- the file itself ----
def test_saving_is_atomic_and_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    creds = {k: "v" * 8 for k in credentials.REQUIRED}
    credentials.save(tmp_path, creds)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["credentials.json"]
    original = (tmp_path / "credentials.json").read_text()

    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        credentials.save(tmp_path, {**creds, "collector_key": "new-key-value"})
    monkeypatch.undo()
    assert (tmp_path / "credentials.json").read_text() == original  # the old file is intact
    assert sorted(p.name for p in tmp_path.iterdir()) == ["credentials.json"]  # and the temp file was cleaned up


def test_the_file_is_restricted_to_its_owner(tmp_path):
    path, restricted = credentials.save(tmp_path, {k: "v" * 8 for k in credentials.REQUIRED})
    assert restricted
    if os.name == "nt":
        acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True).stdout
        assert os.environ["USERNAME"].lower() in acl.lower()
        for broad in ("Everyone", "BUILTIN\\Users", "Authenticated Users"):
            assert broad not in acl, acl
    else:
        assert (path.stat().st_mode & 0o777) == 0o600


def test_incomplete_credentials_are_never_saved(tmp_path):
    with pytest.raises(credentials.CredentialsError):
        credentials.save(tmp_path, {"collector_id": "col-x"})
    assert not credentials.exists(tmp_path)


def test_a_damaged_credentials_file_stops_the_collector_instead_of_falling_back(tmp_path):
    (tmp_path / "credentials.json").write_text("{not json")
    with pytest.raises(credentials.CredentialsError, match="cannot be read"):
        Config(data_dir=tmp_path)
    (tmp_path / "credentials.json").write_text(json.dumps({"collector_id": "col-x"}))
    with pytest.raises(credentials.CredentialsError, match="missing or has empty fields"):
        Config(data_dir=tmp_path)


# ---- first-start enrollment ----
def test_ensure_enrolled_enrolls_on_first_start_then_leaves_the_credentials_alone(certs, tmp_path, monkeypatch):
    with Platform(certs) as p:
        token = p.new_token()
        for k, v in {"ENROLL_TOKEN": token, "ENROLL_TENANT": "t-acme", "SAAS_URL": p.url, "SAAS_CA_FILE": str(certs["ca.pem"]), "DATA_DIR": str(tmp_path)}.items():
            monkeypatch.setenv(k, v)
        cfg = ensure_enrolled(Config())
        assert cfg.credentials_source == "enrolled" and cfg.collector_id == "col-new-01"
        saved = credentials.load(tmp_path)
        assert ensure_enrolled(Config()).collector_key == saved["collector_key"]  # already enrolled: nothing happens
        assert len(p.issued) == 1


def test_no_token_means_no_enrollment_and_a_missing_tenant_is_an_error(certs, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = Config()
    assert ensure_enrolled(cfg) is cfg  # nothing set: unchanged
    monkeypatch.setenv("ENROLL_TOKEN", secrets.token_urlsafe(32))
    with pytest.raises(EnrollmentError, match="ENROLL_TENANT"):
        ensure_enrolled(Config())


def test_a_failed_first_start_enrollment_raises_instead_of_using_dev_defaults(certs, tmp_path, monkeypatch):
    with Platform(certs) as p:
        for k, v in {"ENROLL_TOKEN": secrets.token_urlsafe(32), "ENROLL_TENANT": "t-acme", "SAAS_URL": p.url, "SAAS_CA_FILE": str(certs["ca.pem"]), "DATA_DIR": str(tmp_path)}.items():
            monkeypatch.setenv(k, v)  # a token the platform never issued
        with pytest.raises(EnrollmentError, match="invalid, expired or already used"):
            ensure_enrolled(Config())
        assert not credentials.exists(tmp_path)


# ---- the running collector ----
def test_an_enrolled_collector_signs_with_its_own_key_and_never_exposes_secrets(certs, tmp_path):
    with Platform(certs) as p:
        enroll_and_save(tmp_path, p.url, "t-acme", p.new_token(), ca_file=str(certs["ca.pem"]))
    cfg = Config(data_dir=tmp_path, host_telemetry=False, saas_ca_file=str(certs["ca.pem"]), require_tls=True)
    app = create_app(cfg, run_sender=False)
    saved = credentials.load(tmp_path)
    assert app.state.sender._headers(b"{}")["X-Collector-Key"] == saved["collector_key"] != DEV_COLLECTOR_KEY

    ident = TestClient(app).get("/local/identity").json()
    assert ident["credentials"] == "enrolled" and ident["collector_id"] == "col-new-01" and ident["uses_dev_defaults"] is False
    text = json.dumps(ident)
    for secret in (saved["collector_key"], saved["collector_secret"], saved["pseudo_secret"]):
        assert secret not in text
    for path in ("/local/policy", "/local/retention", "/local/pipeline", "/local/host"):
        assert saved["collector_secret"] not in TestClient(app).get(path).text


def test_the_default_collector_says_it_is_on_dev_credentials():
    app = create_app(Config(data_dir=":memory:", host_telemetry=False), run_sender=False)
    ident = TestClient(app).get("/local/identity").json()
    assert ident["credentials"] == "environment" and ident["uses_dev_defaults"] is True


# ---- the command line ----
def test_cli_succeeds_without_printing_any_secret(certs, tmp_path, capsys):
    with Platform(certs) as p:
        token = p.new_token()
        token_file = tmp_path / "token.txt"
        token_file.write_text(token + "\n")
        code = main(["--saas-url", p.url, "--tenant", "t-acme", "--token-file", str(token_file), "--ca", str(certs["ca.pem"]), "--data-dir", str(tmp_path / "d")])
        out = capsys.readouterr()
        assert code == 0 and "Enrolled col-new-01" in out.out and "token is now spent" in out.out
        for secret in (token, p.issued[0]["key"], p.issued[0]["secret"]):
            assert secret not in out.out + out.err


def test_cli_reports_failures_with_a_nonzero_exit_and_no_token(certs, tmp_path, capsys):
    with Platform(certs) as p:
        token = secrets.token_urlsafe(32)  # never issued
        code = main(["--saas-url", p.url, "--tenant", "t-acme", "--token", token, "--ca", str(certs["ca.pem"]), "--data-dir", str(tmp_path / "d")])
        out = capsys.readouterr()
        assert code == 1 and "enrollment failed" in out.err and token not in out.out + out.err
    assert main(["--saas-url", "https://127.0.0.1:1", "--tenant", "t-acme", "--token-file", str(tmp_path / "missing.txt"), "--data-dir", str(tmp_path / "d2")]) == 2
