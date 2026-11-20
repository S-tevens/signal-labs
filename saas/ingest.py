"""Validate every payload against the frozen contract, then store with dedup."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from .auth import CollectorCred
from .store import Store

_DEFAULT_CONTRACT = Path(__file__).resolve().parent.parent / "contracts" / "payload.schema.json"
MAX_FUTURE_SKEW = timedelta(minutes=5)


def load_validator() -> Draft202012Validator:
    path = Path(os.getenv("CONTRACT_PATH", str(_DEFAULT_CONTRACT)))
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def process_batch(store: Store, validator: Draft202012Validator, cred: CollectorCred, payloads: list) -> dict:
    accepted: list[str] = []
    duplicate: list[str] = []
    rejected: list[dict] = []
    now = datetime.now(timezone.utc)

    for p in payloads:
        pid = p.get("payload_id") if isinstance(p, dict) else None
        errors = sorted(validator.iter_errors(p), key=lambda e: list(e.path)) if isinstance(p, dict) else ["not an object"]
        if errors:
            first = errors[0]
            reason = f"schema: {getattr(first, 'message', first)}"[:200]
            rejected.append({"payload_id": pid, "reason": reason})
            continue
        # Identity comes from the credential. A payload claiming another tenant is rejected, not re-labelled.
        if p["tenant_ref"] != cred.tenant_ref or p["collector_id"] != cred.collector_id:
            rejected.append({"payload_id": pid, "reason": "tenant or collector does not match credential"})
            continue
        ts = datetime.fromisoformat(p["event_ts_utc"].replace("Z", "+00:00"))
        if ts.tzinfo is None or ts.utcoffset() != timedelta(0) or ts - now > MAX_FUTURE_SKEW:
            rejected.append({"payload_id": pid, "reason": "event_ts_utc must be UTC and not in the future"})
            continue
        (accepted if store.insert_payload(cred.tenant_ref, p) else duplicate).append(pid)

    if accepted or duplicate:
        store.touch_collector(cred.tenant_ref, cred.collector_id)
    return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}
