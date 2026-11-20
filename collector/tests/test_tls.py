import asyncio
import socket
import threading
import time
import uuid
from contextlib import contextmanager

import pytest

pytest.importorskip("cryptography")  # only needed to make dev certificates; add it to CI to run these
import uvicorn  # noqa: E402
from cryptography import x509  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402

from collector.config import Config  # noqa: E402
from collector.devcerts import generate  # noqa: E402
from collector.outbox import LocalStore  # noqa: E402
from collector.sender import Sender, TlsRequiredError  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextmanager
def tls_server(certs):
    """A real HTTPS server that behaves like the SaaS ingest endpoint."""
    app = FastAPI()
    received: list[str] = []

    @app.post("/v1/ingest")
    async def ingest(request: Request):
        ids = [p["payload_id"] for p in await request.json()]
        received.extend(ids)
        return {"accepted": ids, "duplicate": [], "conflict": []}

    @app.post("/v1/heartbeat")
    async def heartbeat():
        return {"accepted": True}

    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, ssl_keyfile=str(certs["server.key"]), ssl_certfile=str(certs["server.pem"]), log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "test HTTPS server did not start"
    try:
        yield port, received
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def deliver(cfg):
    """Queue one payload and try to send it. Returns (sender, store, payload_id)."""
    store = LocalStore(":memory:")
    pid = str(uuid.uuid4())
    store.enqueue({"payload_id": pid}, [], [])
    sender = Sender(cfg, store)

    async def go():
        async with sender.make_client() as client:
            await sender.send_once(client)

    asyncio.run(go())
    return sender, store, pid


def cfg_for(port, ca=None, scheme="https", **kw):
    return Config(data_dir=":memory:", saas_url=f"{scheme}://127.0.0.1:{port}", saas_ca_file=str(ca) if ca else "", **kw)


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("good"))


def test_delivery_over_https_with_the_right_ca(certs):
    with tls_server(certs) as (port, received):
        sender, store, pid = deliver(cfg_for(port, certs["ca.pem"], require_tls=True))
        assert received == [pid] and store.depth() == 0
        assert sender.last_error is None and sender.transport.startswith("https")


def test_a_different_ca_is_rejected_and_nothing_is_lost(certs, tmp_path):
    other = generate(tmp_path / "other")  # a perfectly valid CA, just not the one that signed the server
    with tls_server(certs) as (port, received):
        sender, store, pid = deliver(cfg_for(port, other["ca.pem"]))
        assert received == []  # never reached the server
        assert store.depth() == 1  # still buffered, will retry
        assert "CERTIFICATE_VERIFY_FAILED" in (sender.last_error or "")


def test_system_trust_store_does_not_trust_our_private_ca(certs):
    with tls_server(certs) as (port, received):
        sender, store, _ = deliver(cfg_for(port, ca=None))
        assert received == [] and store.depth() == 1 and sender.last_error


def test_certificate_for_another_name_is_rejected(tmp_path):
    wrong_name = generate(tmp_path / "wrong", sans=("example.test",))  # valid CA chain, but not for 127.0.0.1
    with tls_server(wrong_name) as (port, received):
        sender, store, _ = deliver(cfg_for(port, wrong_name["ca.pem"]))
        assert received == [] and store.depth() == 1
        assert "verif" in (sender.last_error or "").lower() or "hostname" in (sender.last_error or "").lower()


def test_plain_http_to_a_tls_port_fails_and_buffers(certs):
    with tls_server(certs) as (port, received):
        sender, store, _ = deliver(cfg_for(port, scheme="http"))
        assert received == [] and store.depth() == 1 and sender.last_error


def test_require_tls_refuses_an_http_url_at_startup():
    with pytest.raises(TlsRequiredError):
        Sender(Config(data_dir=":memory:", saas_url="http://127.0.0.1:8000", require_tls=True), LocalStore(":memory:"))
    Sender(Config(data_dir=":memory:", saas_url="https://127.0.0.1:8000", require_tls=True), LocalStore(":memory:"))  # fine


def test_plain_http_is_allowed_only_when_tls_is_not_required_and_is_labelled():
    s = Sender(Config(data_dir=":memory:", saas_url="http://127.0.0.1:8000", require_tls=False), LocalStore(":memory:"))
    assert "NOT ENCRYPTED" in s.transport


# ---- the certificate generator ----
def test_generated_certificates_are_a_valid_chain_with_the_right_names(certs):
    server = x509.load_pem_x509_certificate(certs["server.pem"].read_bytes())
    ca = x509.load_pem_x509_certificate(certs["ca.pem"].read_bytes())
    server.verify_directly_issued_by(ca)
    san = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert any(str(ip) == "127.0.0.1" for ip in san.get_values_for_type(x509.IPAddress))
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    assert server.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False


def test_generation_is_idempotent_and_force_replaces(tmp_path):
    first = generate(tmp_path)
    serial = x509.load_pem_x509_certificate(first["server.pem"].read_bytes()).serial_number
    again = generate(tmp_path)
    assert x509.load_pem_x509_certificate(again["server.pem"].read_bytes()).serial_number == serial
    forced = generate(tmp_path, force=True)
    assert x509.load_pem_x509_certificate(forced["server.pem"].read_bytes()).serial_number != serial
