"""parse -> store raw (local) -> redact -> map to allow-list -> validate -> outbox.

Aggregation windows and local analysis (e.g. failed-login bursts) are the next step;
today each record becomes one payload with window_s=1.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from .config import COLLECTOR_VERSION, Config
from .outbox import LocalStore
from .parsers import parse_line
from .redact import pseudonym, redact
from .schema import METRIC_NAMES, METRIC_UNITS, Payload

AUTH_FAIL = re.compile(r"(?i)(failed password|authentication failure|invalid (user|password)|login failed)")


def _event_time(record: dict) -> datetime:
    raw = record.get("ts")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class Pipeline:
    def __init__(self, cfg: Config, store: LocalStore):
        self.cfg = cfg
        self.store = store

    def process(self, line: str) -> dict:
        line = line.strip()
        if not line:
            return {"status": "empty"}

        record = parse_line(line)
        _, rules = redact(line)  # which rules fire on the raw line; the raw line itself stays local
        raw_id = self.store.add_raw(line, rules)

        payload = self._to_payload(record)
        if payload is None:
            return {"status": "dropped", "raw_id": raw_id, "format": record.get("format")}
        self.store.enqueue(payload, raw_id, rules)
        return {"status": "queued", "raw_id": raw_id, "payload_id": payload["payload_id"], "format": record.get("format")}

    def _to_payload(self, record: dict) -> dict | None:
        kind = record.get("kind")
        base = {
            "payload_id": str(uuid.uuid4()),
            "tenant_ref": self.cfg.tenant_ref,
            "collector_id": self.cfg.collector_id,
            "source_id": pseudonym(str(record.get("host") or "unknown"), self.cfg.pseudo_secret),
            "region": self.cfg.region,
            "event_ts_utc": _event_time(record),
            "source_tz": record.get("tz") or "UTC",
            "window_s": 1,
            "health_state": "Good",
            "collector_version": COLLECTOR_VERSION,
        }

        if kind == "metric":
            name = record.get("name")
            try:
                value = float(record.get("value"))
            except (TypeError, ValueError):
                return None
            if name not in METRIC_NAMES:
                return None  # not on the allow-list: dropped, never sent
            base["metric"] = {"name": name, "value": value, "unit": METRIC_UNITS[name]}
        elif kind == "log":
            message = str(record.get("message") or "")
            is_auth = bool(AUTH_FAIL.search(message))
            category = "auth_failure" if is_auth else "log_event"
            # Summary is a template. Raw message text has no path into the payload.
            base["event"] = {
                "category": category,
                "severity": "warning" if is_auth else "info",
                "count": 1,
                "summary": category.replace("_", " ") + " observed",
            }
        else:
            return None  # heartbeats etc. are handled elsewhere

        try:
            return Payload(**base).model_dump(mode="json", exclude_none=True)
        except ValidationError:
            return None
