"""Format-agnostic input. One small file per format; adding a format never touches another file.

A parser exposes:
    detect(line: str) -> bool
    parse(line: str) -> dict   # normalized record, see below

Normalized record keys (all optional except kind):
    kind:    "metric" | "log" | "heartbeat"
    ts:      ISO-8601 string (UTC assumed if no offset); missing means "now"
    tz:      source timezone name
    host:    originating host (pseudonymized before leaving)
    name, value:  for metrics
    message: for logs (never leaves the collector)
"""
from __future__ import annotations

from . import json_parser, kv_parser, syslog_parser, text_parser

# Order matters: most specific first, plain text is the fallback.
PARSERS = [json_parser, syslog_parser, kv_parser, text_parser]


def parse_records(line: str, csv_header: list[str] | None = None) -> list[dict]:
    """A line can yield several records (a wide row has one metric per column). Never raises."""
    from .. import mapping

    if csv_header:
        rows = mapping.get().parse_csv_row(csv_header, line)
        if rows:
            for r in rows:
                r.setdefault("format", "csv")
            return rows
    for parser in PARSERS:
        if parser.detect(line):
            try:
                records = parser.parse_many(line) if hasattr(parser, "parse_many") else [parser.parse(line)]
            except Exception:  # a bad line must never stop the stream
                continue
            for r in records:
                r.setdefault("format", parser.__name__.rsplit(".", 1)[-1].removesuffix("_parser"))
            return records
    return [text_parser.parse(line)]


def parse_line(line: str) -> dict:
    for parser in PARSERS:
        if parser.detect(line):
            try:
                record = parser.parse(line)
            except Exception:  # a bad line must never stop the stream
                continue
            record.setdefault("format", parser.__name__.rsplit(".", 1)[-1].removesuffix("_parser"))
            return record
    return text_parser.parse(line)
