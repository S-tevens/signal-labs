"""parse -> keep raw (local) -> redact -> aggregate per window -> analyse locally -> policy -> validate -> outbox.

Records are buffered per source and window (aggregate.py) and only become payloads when a window closes,
so 40 failed-login lines become one `auth_failure_burst` event with count=40.
"""
from __future__ import annotations

import time
import uuid
from collections import Counter
from datetime import datetime, timezone

from pydantic import ValidationError

from .aggregate import Aggregator, Window
from .config import COLLECTOR_VERSION, Config
from .local_analysis import SUMMARY, classify_auth, is_auth_failure
from .outbox import LocalStore
from . import mapping
from . import health
from .parsers import parse_line, parse_records
from .policy import Policy
from .redact import pseudonym, redact
from .schema import METRIC_NAMES, METRIC_UNITS, Payload


def _event_epoch(record: dict) -> float:
    raw = record.get("ts")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    return time.time()


class Pipeline:
    def __init__(self, cfg: Config, store: LocalStore, policy: Policy | None = None):
        self.cfg = cfg
        self.store = store
        self.policy = policy or Policy.load(cfg.policy_file)
        self.agg = Aggregator(cfg.window_s, cfg.grace_s)
        self.counters: Counter[str] = Counter()

    # ---- intake ----
    def process(self, line: str) -> dict:
        """Text sent to /ingest, in any supported format."""
        line = line.strip()
        if not line:
            return {"status": "empty"}
        if len(line) > self.cfg.max_line_chars:
            # Never parse, redact or aggregate an enormous line: it is a flood or an attack, and the regexes would run
            # over megabytes. Keep a short marker so the operator can see it happened.
            self.counters["received"] += 1
            self.counters["oversize"] += 1
            marker = f"{line[:512]} ...[line of {len(line)} characters dropped: over the {self.cfg.max_line_chars} limit]"
            raw_id = self.store.add_raw(marker, [])
            return {"status": "dropped_oversize", "raw_id": raw_id}
        return self._process_parsed(line, parse_records(line))

    def process_text(self, text: str, state: dict | None = None) -> list[dict]:
        """Many lines from one source. A CSV header line sets the column names for the lines after it (kept in `state`)."""
        state = state if state is not None else {}
        results = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if len(line) <= self.cfg.max_line_chars and not line.startswith("{") and mapping.get().looks_like_header(line):
                state["csv_header"] = [c.strip().strip('"') for c in line.split(",")]
                results.append({"status": "csv_header"})
                continue
            if len(line) > self.cfg.max_line_chars:
                results.append(self.process(line))
            else:
                results.append(self._process_parsed(line, parse_records(line, state.get("csv_header"))))
        return results

    def _process_parsed(self, line: str, records: list[dict]) -> dict:
        results = [self.process_record(r, line) for r in records]
        return results[0] if len(results) == 1 else {**results[0], "records": len(results)}

    def process_record(self, record: dict, line: str) -> dict:
        """A normalized record (from a parser or a source such as host telemetry). `line` is the local raw text."""
        self.counters["received"] += 1
        fmt = record.get("format")
        self.counters[f"format:{fmt}"] += 1
        _, rules = redact(line, self.policy.redaction_rules)  # which rules fire; the raw line itself stays local
        raw_id = self.store.add_raw(line, rules)

        source = pseudonym(str(record.get("host") or "unknown"), self.cfg.pseudo_secret)
        ts = _event_epoch(record)
        tz = record.get("tz") or "UTC"
        kind = record.get("kind")

        if kind == "metric":
            name = record.get("name")
            try:
                value = float(record.get("value"))
            except (TypeError, ValueError):
                value = None
            if name not in METRIC_NAMES or value is None or value != value:  # unknown name, bad number or NaN
                self.counters["dropped"] += 1
                return {"status": "dropped", "raw_id": raw_id, "format": fmt}
            ready = self.agg.add_metric(source, name, value, ts, tz, raw_id, rules)
        elif kind == "log":
            ready = self.agg.add_log(source, is_auth_failure(str(record.get("message") or "")), ts, tz, raw_id, rules)
        else:
            self.counters["dropped"] += 1
            return {"status": "dropped", "raw_id": raw_id, "format": fmt}

        for window in ready:  # only late arrivals come back immediately
            self._emit(window)
        return {"status": "aggregated", "raw_id": raw_id, "format": fmt}

    # ---- output ----
    def flush(self, force: bool = False) -> int:
        """Send every window that has closed (all of them if force). Returns the number of payloads queued."""
        queued = 0
        for window in self.agg.flush(time.time(), force=force):
            queued += self._emit(window)
        return queued

    def _emit(self, w: Window) -> int:
        self.counters["windows"] += 1
        body = {
            "payload_id": str(uuid.uuid4()),
            "tenant_ref": self.cfg.tenant_ref,
            "collector_id": self.cfg.collector_id,
            "source_id": w.source,
            "region": self.cfg.region,
            "event_ts_utc": datetime.fromtimestamp(w.last_ts, timezone.utc),
            "source_tz": w.tz,
            "window_s": 1 if w.late else self.cfg.window_s,
            "health_state": "Good",
            "collector_version": COLLECTOR_VERSION,
        }
        if w.kind == "metric":
            body["metric"] = {"name": w.name, "value": w.value, "unit": METRIC_UNITS[w.name]}
            body["health_state"] = health.metric_state(w.name, w.value)
        elif w.kind == "auth":
            category, severity = classify_auth(w.n, self.cfg.burst_threshold)
            body["event"] = {"category": category, "severity": severity, "count": w.n, "summary": SUMMARY[category]}
            body["health_state"] = health.event_state(severity)
        else:
            body["event"] = {"category": "log_event", "severity": "info", "count": w.n, "summary": SUMMARY["log_event"]}

        return self._queue(body, w.raw_ids, w.rules)

    def _queue(self, body: dict, raw_ids: list[int], rules) -> int:
        """Schema check, then the customer's policy, then the outbox. Every payload goes through here."""
        try:
            checked = Payload(**body).model_dump(mode="json", exclude_none=True)
        except ValidationError:
            self.counters["invalid"] += 1
            return 0
        decision = self.policy.apply(checked)  # second gate: this customer's allow-list
        if decision.blocked:
            self.counters["blocked_by_policy"] += 1
            return 0
        self.store.enqueue(decision.payload, raw_ids, sorted(rules))
        self.counters["payloads"] += 1
        return 1

    def emit_collector_event(self, category: str, severity: str, count: int, summary: str) -> bool:
        """The collector reporting on itself, for example that it had to drop data. Same gates as any payload."""
        body = {
            "payload_id": str(uuid.uuid4()),
            "tenant_ref": self.cfg.tenant_ref,
            "collector_id": self.cfg.collector_id,
            "source_id": pseudonym(self.cfg.host_label, self.cfg.pseudo_secret),
            "region": self.cfg.region,
            "event_ts_utc": datetime.now(timezone.utc),
            "source_tz": self.cfg.source_tz,
            "window_s": self.cfg.window_s,
            "health_state": health.event_state(severity),
            "collector_version": COLLECTOR_VERSION,
            "event": {"category": category, "severity": severity, "count": max(1, min(int(count), 1_000_000)), "summary": summary},
        }
        return bool(self._queue(body, [], []))
