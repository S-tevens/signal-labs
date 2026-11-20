"""Authenticated delivery: signed batches, retry with backoff, heartbeat."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx

from .config import COLLECTOR_VERSION, Config
from .outbox import LocalStore


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Sender:
    def __init__(self, cfg: Config, store: LocalStore):
        self.cfg = cfg
        self.store = store
        self.link_up = True  # demo switch for the "SaaS outage" scenario
        self.last_send_utc: str | None = None
        self.last_error: str | None = None

    def _headers(self, body: bytes) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Collector-Key": self.cfg.collector_key,
            "X-Signature": sign(self.cfg.collector_secret, body),
        }

    async def send_once(self, client: httpx.AsyncClient) -> None:
        if not self.link_up:
            return
        batch = self.store.pending(self.cfg.batch_size)
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
        async with httpx.AsyncClient(timeout=5.0) as client:
            last_hb = 0.0
            loop = asyncio.get_running_loop()
            while True:
                await self.send_once(client)
                if loop.time() - last_hb >= self.cfg.heartbeat_interval_s:
                    await self.heartbeat_once(client)
                    last_hb = loop.time()
                await asyncio.sleep(self.cfg.send_interval_s)
