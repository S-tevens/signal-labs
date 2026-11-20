"""Authenticated delivery: signed batches, retry with backoff, heartbeat."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import ssl
import time
from datetime import datetime, timezone

import httpx

from .config import COLLECTOR_VERSION, Config
from .outbox import LocalStore, digest_of

log = logging.getLogger("collector.sender")


class TlsRequiredError(RuntimeError):
    """REQUIRE_TLS is on but the SaaS URL is not https. The collector refuses to start rather than send in clear."""


def tls_context(ca_file: str = "") -> ssl.SSLContext:
    """Verifying TLS context, TLS 1.2 minimum. With a CA file only that CA is trusted, otherwise the system store."""
    ctx = ssl.create_default_context(cafile=ca_file or None)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


HOLD_MAX_S = 300.0  # a hold releases itself after five minutes so a forgotten hold cannot silence the collector


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Sender:
    def __init__(self, cfg: Config, store: LocalStore):
        self.cfg = cfg
        self.store = store
        self.link_up = True  # demo switch for the "SaaS outage" scenario
        self.last_send_utc: str | None = None
        self.last_error: str | None = None
        self.held_since: float | None = None  # monotonic-free wall clock; None means sending normally
        self.hold_max_s = HOLD_MAX_S
        self.last_release: dict | None = None
        self.https = cfg.saas_url.lower().startswith("https://")
        if cfg.require_tls and not self.https:
            raise TlsRequiredError(f"REQUIRE_TLS=1 but SAAS_URL is {cfg.saas_url!r}; use an https:// URL")
        if not self.https:
            log.warning("SaaS link is plain HTTP: payloads are authenticated and signed but NOT encrypted")

    # --- hold / release (E18): a person can stop payloads leaving, look at them, then let them go ---
    def hold(self) -> dict:
        if self.held_since is None:
            self.held_since = time.time()
        return self.hold_state()

    def release(self, reason: str = "released by operator") -> dict:
        if self.held_since is not None:
            held_for = time.time() - self.held_since
            self.last_release = {"at_utc": datetime.now(timezone.utc).isoformat(), "reason": reason, "held_for_s": round(held_for, 1)}
        self.held_since = None
        return self.hold_state()

    def hold_state(self) -> dict:
        """Held or not, and how long until the automatic release. Expires the hold as a side effect."""
        if self.held_since is not None and time.time() - self.held_since >= self.hold_max_s:
            self.release("auto-release after the maximum hold time")
        held = self.held_since is not None
        return {
            "held": held,
            "held_since_utc": datetime.fromtimestamp(self.held_since, timezone.utc).isoformat() if held else None,
            "auto_release_in_s": round(max(0.0, self.hold_max_s - (time.time() - self.held_since)), 1) if held else None,
            "max_hold_s": self.hold_max_s,
            "last_release": self.last_release,
        }

    @property
    def transport(self) -> str:
        if not self.https:
            return "http (NOT ENCRYPTED)"
        return "https (server verified against " + (self.cfg.saas_ca_file or "the system trust store") + ")"

    def make_client(self) -> httpx.AsyncClient:
        """HTTPS always verifies the server certificate and name. There is deliberately no switch to turn that off.

        With SAAS_CA_FILE set, only that CA is trusted (the system store is not consulted), so a certificate from any
        other authority is rejected. TLS 1.2 is the minimum.
        """
        verify: ssl.SSLContext | bool = tls_context(self.cfg.saas_ca_file) if self.https else True
        return httpx.AsyncClient(timeout=5.0, verify=verify)

    def _headers(self, body: bytes) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Collector-Key": self.cfg.collector_key,
            "X-Signature": sign(self.cfg.collector_secret, body),
        }

    async def send_once(self, client: httpx.AsyncClient) -> None:
        if not self.link_up or self.hold_state()["held"]:
            return
        rows = self.store.pending_rows(self.cfg.batch_size)
        # Send only what was queued: a body that no longer matches its queue-time digest is never sent.
        batch = []
        for payload, digest in rows:
            if digest and digest_of(payload) != digest:
                self.store.mark_rejected(payload["payload_id"], "digest mismatch: queued body was altered")
                self.last_error = f"payload {payload['payload_id'][:8]} altered after queueing; not sent"
                continue
            batch.append(payload)
        if not batch:
            return
        ids = [p["payload_id"] for p in batch]
        # The SaaS takes a JSON array of 1-500 payloads. The signature covers these exact bytes.
        body = json.dumps(batch, sort_keys=True, separators=(",", ":")).encode()
        try:
            resp = await client.post(f"{self.cfg.saas_url}/v1/ingest", content=body, headers=self._headers(body))
            if resp.status_code in (400, 413, 415, 422) and len(batch) > 1:
                # A batch-level rejection: one bad payload fails the whole request. Retry per payload
                # so a single bad record cannot block the rest of the buffer.
                await self._send_individually(client, batch)
                return
            resp.raise_for_status()
            result = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.last_error = str(exc)[:200]
            self.store.mark_failed(ids)
            return
        self._apply(ids, result)

    def _apply(self, ids: list[str], result: dict) -> None:
        # accepted and duplicate both mean the SaaS has it. A conflict (same ID, different body)
        # will never succeed on retry, so it is closed out and surfaced instead of looping forever.
        conflict = set(result.get("conflict", []))
        done = set(result.get("accepted", [])) | set(result.get("duplicate", [])) | conflict
        self.store.mark_sent([i for i in ids if i in done])
        self.store.mark_failed([i for i in ids if i not in done])
        self.last_send_utc = datetime.now(timezone.utc).isoformat()
        self.last_error = f"{len(conflict)} payload(s) conflicted: same ID, different body" if conflict else None

    async def _send_individually(self, client: httpx.AsyncClient, batch: list[dict]) -> None:
        for p in batch:
            body = json.dumps([p], sort_keys=True, separators=(",", ":")).encode()
            try:
                resp = await client.post(f"{self.cfg.saas_url}/v1/ingest", content=body, headers=self._headers(body))
            except httpx.HTTPError as exc:
                self.last_error = str(exc)[:200]
                self.store.mark_failed([p["payload_id"]])
                continue
            if resp.status_code == 200:
                self._apply([p["payload_id"]], resp.json())
            elif resp.status_code in (400, 403, 413, 415, 422):
                # Permanently invalid for this SaaS: drop from the buffer and surface the reason.
                self.store.mark_rejected(p["payload_id"], f"HTTP {resp.status_code}")
                self.last_error = f"payload {p['payload_id'][:8]} rejected by SaaS: HTTP {resp.status_code}"
            else:
                self.store.mark_failed([p["payload_id"]])

    async def heartbeat_once(self, client: httpx.AsyncClient) -> None:
        if not self.link_up:
            return
        body = json.dumps(
            {
                "collector_id": self.cfg.collector_id,
                "collector_version": COLLECTOR_VERSION,
                "config_hash": "dev",
                "resource_usage": {},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        try:
            await client.post(f"{self.cfg.saas_url}/v1/heartbeat", content=body, headers=self._headers(body))
        except httpx.HTTPError as exc:
            self.last_error = str(exc)[:200]

    async def run(self) -> None:
        async with self.make_client() as client:
            last_hb = 0.0
            loop = asyncio.get_running_loop()
            while True:
                await self.send_once(client)
                if loop.time() - last_hb >= self.cfg.heartbeat_interval_s:
                    await self.heartbeat_once(client)
                    last_hb = loop.time()
                await asyncio.sleep(self.cfg.send_interval_s)
