from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException


@dataclass(frozen=True)
class CollectorCred:
    tenant_ref: str
    collector_id: str
    secret: str


class Auth:
    def __init__(self, tenants_file: str | Path):
        data = json.loads(Path(tenants_file).read_text(encoding="utf-8"))
        self._collectors = {k: CollectorCred(**v) for k, v in data["collectors"].items()}
        self._dashboards: dict[str, str] = data["dashboard_tokens"]

    def collector(self, key: str | None, signature: str | None, body: bytes) -> CollectorCred:
        cred = self._collectors.get(key or "")
        if cred is None or not signature:
            raise HTTPException(401, "invalid credentials")
        expected = hmac.new(cred.secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            raise HTTPException(401, "invalid signature")
        return cred

    def dashboard(self, token: str | None) -> str:
        """Return the tenant id this dashboard token is bound to."""
        tenant = self._dashboards.get(token or "")
        if tenant is None:
            raise HTTPException(401, "invalid dashboard token")
        return tenant
