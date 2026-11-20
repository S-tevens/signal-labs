"""Windowed aggregation: many records in, one summary per source and window out.

Why: sending one payload per record multiplies volume and leaks fine-grained timing.
A window is closed by event time (not arrival time) once `window_end + grace` has passed,
so late and reordered events still land in the right window.

Summary rules (the schema carries a single value per metric payload):
  * gauges (cpu, memory, latency, ...) -> mean of the window
  * booleans (service_up, connectivity_up) -> minimum, so any failure shows up
A record that arrives after its window was already sent is emitted on its own (marked late)
instead of being dropped or silently merged into an earlier summary.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

BOOL_METRICS = {"service_up", "connectivity_up"}
_CLOSED_MEMORY = 20_000  # how many sent windows we remember, to recognise late arrivals


@dataclass
class Window:
    kind: str  # "metric" | "auth" | "log"
    source: str
    name: str  # metric name; empty for logs
    start: float
    tz: str = "UTC"
    n: int = 0
    total: float = 0.0
    low: float = float("inf")
    last_ts: float = 0.0
    raw_ids: list[int] = field(default_factory=list)
    rules: set[str] = field(default_factory=set)
    late: bool = False

    def add(self, value: float, ts: float, raw_id: int | None, rules: list[str]) -> None:
        self.n += 1
        self.total += value
        self.low = min(self.low, value)
        self.last_ts = max(self.last_ts, ts)
        if raw_id is not None:
            self.raw_ids.append(raw_id)
        self.rules.update(rules)

    @property
    def value(self) -> float:
        if self.name in BOOL_METRICS:
            return self.low
        return round(self.total / self.n, 4) if self.n else 0.0


class Aggregator:
    def __init__(self, window_s: int, grace_s: float):
        self.window_s = max(1, int(window_s))
        self.grace_s = grace_s
        self._open: dict[tuple, Window] = {}
        self._closed: OrderedDict[tuple, None] = OrderedDict()
        self._lock = threading.Lock()

    def _start(self, ts: float) -> float:
        return (int(ts) // self.window_s) * self.window_s

    def _add(self, kind: str, source: str, name: str, value: float, ts: float, tz: str, raw_id, rules) -> list[Window]:
        start = self._start(ts)
        key = (kind, source, name, start)
        with self._lock:
            if key in self._closed:
                # Its window is already on the wire: send this record alone rather than lose it.
                solo = Window(kind, source, name, start, tz, late=True)
                solo.add(value, ts, raw_id, rules)
                return [solo]
            win = self._open.get(key)
            if win is None:
                win = self._open[key] = Window(kind, source, name, start, tz)
            win.add(value, ts, raw_id, rules)
            return []

    def add_metric(self, source, name, value, ts, tz="UTC", raw_id=None, rules=()) -> list[Window]:
        return self._add("metric", source, name, float(value), ts, tz, raw_id, list(rules))

    def add_log(self, source, is_auth_failure, ts, tz="UTC", raw_id=None, rules=()) -> list[Window]:
        # Log text is never kept here, only counted. The text stays in the local raw store.
        return self._add("auth" if is_auth_failure else "log", source, "", 1.0, ts, tz, raw_id, list(rules))

    def flush(self, now: float, force: bool = False) -> list[Window]:
        """Close and return every window whose end plus grace has passed (all of them if force)."""
        with self._lock:
            ready = [
                (key, win)
                for key, win in self._open.items()
                if force or win.start + self.window_s + self.grace_s <= now
            ]
            for key, _ in ready:
                del self._open[key]
                self._closed[key] = None
            while len(self._closed) > _CLOSED_MEMORY:
                self._closed.popitem(last=False)
        return [win for _, win in sorted(ready, key=lambda kv: kv[1].start)]

    def open_windows(self) -> int:
        with self._lock:
            return len(self._open)
