"""Input mapping (E16): a new stream format needs configuration, not code.

`mapping.yaml` says which field names carry the host, metric name, value, time and message, how metric names and units
map to ours (aliases, scale, offset), and which timestamp formats to try. Anything not mapped is dropped: unknown fields
never reach the pipeline, so they cannot reach a payload.

Set MAPPING_FILE to use another file.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .schema import METRIC_NAMES

DEFAULT_FILE = Path(__file__).with_name("mapping.yaml")
_FIELD_LISTS = ("host_fields", "name_fields", "value_fields", "time_fields", "message_fields")


class MappingError(ValueError):
    """The mapping file is wrong. Fail at start, not on the first record."""


class Mapping:
    def __init__(self, data: dict):
        unknown = set(data) - set(_FIELD_LISTS) - {"timestamp_formats", "default_tz", "metrics"}
        if unknown:
            raise MappingError(f"unknown mapping key(s): {sorted(unknown)}")
        for key in _FIELD_LISTS:
            value = data.get(key)
            if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
                raise MappingError(f"{key} must be a non-empty list of field names")
            setattr(self, key, [v.lower() for v in value])
        self.timestamp_formats = [str(f) for f in data.get("timestamp_formats", [])]
        self.metrics: dict[str, tuple[str, float, float]] = {}
        for alias, spec in (data.get("metrics") or {}).items():
            spec = {"name": spec} if isinstance(spec, str) else dict(spec or {})
            name = spec.pop("name", None)
            scale, offset = spec.pop("scale", 1), spec.pop("offset", 0)
            if spec or name not in METRIC_NAMES or not all(isinstance(x, (int, float)) for x in (scale, offset)):
                raise MappingError(f"metric alias {alias!r}: needs name (one of {list(METRIC_NAMES)}) and numeric scale/offset only")
            self.metrics[str(alias).lower()] = (name, float(scale), float(offset))
        for name in METRIC_NAMES:  # our own names always map to themselves
            self.metrics.setdefault(name, (name, 1.0, 0.0))

    # ---- fields ----
    def pick(self, data: dict, candidates: list[str]):
        lowered = {str(k).lower(): v for k, v in data.items()}
        for c in candidates:
            if c in lowered and lowered[c] not in (None, ""):
                return lowered[c]
        return None

    def known_fields(self) -> set[str]:
        return set(self.host_fields + self.name_fields + self.value_fields + self.time_fields + self.message_fields) | set(self.metrics)

    def timestamp(self, raw) -> str | None:
        """Any supported time form -> ISO-8601 UTC string, or None (the pipeline then stamps arrival time)."""
        if raw is None or raw == "":
            return None
        try:
            number = float(raw)
        except (TypeError, ValueError):
            number = None
        if number is not None and not isinstance(raw, bool):
            for limit, div in ((1e11, 1), (1e14, 1e3), (1e17, 1e6), (1e20, 1e9)):  # seconds, ms, us, ns
                if abs(number) < limit:
                    return _iso(number / div)
            return None
        text = str(raw).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return _iso(_aware(dt).timestamp())
        except ValueError:
            pass
        for fmt in self.timestamp_formats:
            try:
                return _iso(_aware(datetime.strptime(text, fmt)).timestamp())
            except ValueError:
                continue
        return None

    # ---- records ----
    def normalize(self, data: dict, line: str | None = None) -> list[dict]:
        """One field map -> zero or more normalized records. Metrics may arrive as name/value or as one column each."""
        host = self.pick(data, self.host_fields) or "unknown"
        ts = self.timestamp(self.pick(data, self.time_fields))
        base = {"ts": ts, "tz": data.get("tz"), "host": str(host)}
        explicit_kind = str(data.get("kind") or "").lower()
        records: list[dict] = []
        if explicit_kind != "log":
            name, value = self.pick(data, self.name_fields), self.pick(data, self.value_fields)
            if name is not None and value is not None:
                records.append({**base, "kind": "metric", **self._convert(str(name), value)})
            lowered = {str(k).lower(): v for k, v in data.items()}
            for key, value in lowered.items():  # wide row: one column per metric
                if key in self.metrics and key not in self.name_fields and key not in self.value_fields and value not in (None, ""):
                    records.append({**base, "kind": "metric", **self._convert(key, value)})
        if not records:
            message = self.pick(data, self.message_fields)
            records.append({**base, "kind": "log", "message": str(message) if message is not None else (line or "")})
        return records

    def _convert(self, alias: str, value) -> dict:
        name, scale, offset = self.metrics.get(alias.lower(), (alias, 1.0, 0.0))
        try:
            number = float(value) * scale + offset
        except (TypeError, ValueError):
            number = value  # the pipeline drops it as a bad number
        return {"name": name, "value": number}

    # ---- csv ----
    def looks_like_header(self, line: str) -> bool:
        cells = [c.strip().strip('"').lower() for c in line.split(",")]
        if len(cells) < 2 or any(not re.fullmatch(r"[\w@. -]+", c) or re.fullmatch(r"[\d.\-]+", c) for c in cells):
            return False
        return any(c in self.known_fields() for c in cells)

    def parse_csv_row(self, header: list[str], line: str) -> list[dict] | None:
        try:
            row = next(csv.reader(io.StringIO(line)))
        except (csv.Error, StopIteration):
            return None
        if len(row) != len(header):
            return None
        return self.normalize(dict(zip(header, row)), line)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


_current: Mapping | None = None
_current_path: str | None = None


def load(path: str | os.PathLike | None = None) -> Mapping:
    try:
        data = yaml.safe_load(Path(path or DEFAULT_FILE).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise MappingError(f"cannot read the mapping file: {exc}") from None
    return Mapping(data)


def get() -> Mapping:
    """The mapping in force (MAPPING_FILE, or the default), loaded once."""
    global _current, _current_path
    path = os.getenv("MAPPING_FILE") or str(DEFAULT_FILE)
    if _current is None or _current_path != path:
        _current, _current_path = load(path), path
    return _current
