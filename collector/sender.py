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
        body = json.dumps({"payloads": batch}, sort_keys=True, separators=(",", ":")).encode()
        try:
            resp = await client.post(f"{self.cfg.saas_url}/v1/ingest", content=body, headers=self._headers(body))
            resp.raise_for_status()
            result = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.last_error = str(exc)[:200]
            self.store.mark_failed(ids)
            return
        # Accepted and duplicate both mean the SaaS has it. Rejected ones will not succeed on retry.
        done = set(result.get("accepted", [])) | set(result.get("duplicate", []))
        done |= {r["payload_id"] for r in result.get("rejected", []) if "payload_id" in r}
        self.store.mark_sent([i for i in ids if i in done])
        self.store.mark_failed([i for i in ids if i not in done])
        self.last_send_utc = datetime.now(timezone.utc).isoformat()
        self.last_error = None

    async def heartbeat_once(self, client: httpx.AsyncClient) -> None:
        if not self.link_up:
            return
        body = json.dumps(
            {
                "collector_id": self.cfg.collector_id,
                "version": COLLECTOR_VERSION,
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "config_hash": "dev",
                "buffer_depth": self.store.depth(),
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
