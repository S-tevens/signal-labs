"""Tenant-scoped storage (Postgres in compose, SQLite in tests).

Isolation rule: every public function takes tenant_id as its first argument and every
query filters on it. There is no function that reads across tenants.
Dedup rule: (tenant_id, payload_id) is the primary key, so any replica rejects a duplicate.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import StaticPool

metadata = MetaData()

events = Table(
    "events",
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("payload_id", String(36), primary_key=True),
    Column("collector_id", String(64), nullable=False),
    Column("source_id", String(32), nullable=False),
    Column("region", String(16), nullable=False),
    Column("event_ts", DateTime, nullable=False),  # naive UTC, ordering key
    Column("received_at", DateTime, nullable=False),  # naive UTC, for latency measurement only
    Column("source_tz", String(64), nullable=False),
    Column("window_s", Integer, nullable=False),
    Column("kind", String(8), nullable=False),  # metric | event
    Column("name", String(32)),
    Column("value", Float),
    Column("unit", String(8)),
    Column("category", String(32)),
    Column("severity", String(16)),
    Column("count", Integer),
    Column("summary", String(120)),
    Column("health_state", String(16), nullable=False),
    Column("collector_version", String(16), nullable=False),
)
Index("events_tenant_ts", events.c.tenant_id, events.c.event_ts)

collectors = Table(
    "collectors",
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("collector_id", String(64), primary_key=True),
    Column("last_seen", DateTime, nullable=False),
    Column("version", String(16)),
    Column("buffer_depth", Integer),
    Column("config_hash", String(64)),
)


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_ts(value: str) -> datetime:
    return _naive_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


class Store:
    def __init__(self, database_url: str):
        kwargs = {}
        if database_url.startswith("sqlite") and ":memory:" in database_url:
            kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        elif database_url.startswith("sqlite:///"):
            Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, future=True, pool_pre_ping=True, **kwargs)
        self._create_tables()

    def _create_tables(self) -> None:
        # Several replicas start at once; creation can race, so retry.
        for attempt in range(10):
            try:
                metadata.create_all(self.engine, checkfirst=True)
                return
            except (OperationalError, IntegrityError):
                time.sleep(0.5 * (attempt + 1))
        metadata.create_all(self.engine, checkfirst=True)

    def insert_payload(self, tenant_id: str, p: dict) -> bool:
        """Return True if stored, False if it was a duplicate."""
        row = {
            "tenant_id": tenant_id,
            "payload_id": p["payload_id"],
            "collector_id": p["collector_id"],
            "source_id": p["source_id"],
            "region": p["region"],
            "event_ts": parse_ts(p["event_ts_utc"]),
            "received_at": _utcnow(),
            "source_tz": p["source_tz"],
            "window_s": p["window_s"],
            "health_state": p["health_state"],
            "collector_version": p["collector_version"],
        }
        if "metric" in p:
            m = p["metric"]
            row.update(kind="metric", name=m["name"], value=m["value"], unit=m["unit"])
        else:
            e = p["event"]
            row.update(kind="event", category=e["category"], severity=e["severity"], count=e["count"], summary=e["summary"])
        try:
            with self.engine.begin() as conn:  # own transaction per row: a duplicate must not poison the batch
                conn.execute(insert(events).values(**row))
            return True
        except IntegrityError:
            return False

    def upsert_heartbeat(self, tenant_id: str, collector_id: str, version: str | None, buffer_depth: int | None, config_hash: str | None) -> None:
        values = dict(last_seen=_utcnow(), version=version, buffer_depth=buffer_depth, config_hash=config_hash)
        with self.engine.begin() as conn:
            res = conn.execute(
                collectors.update()
                .where(collectors.c.tenant_id == tenant_id, collectors.c.collector_id == collector_id)
                .values(**values)
            )
            if res.rowcount == 0:
                conn.execute(insert(collectors).values(tenant_id=tenant_id, collector_id=collector_id, **values))

    def touch_collector(self, tenant_id: str, collector_id: str) -> None:
        """Receiving data counts as liveness."""
        with self.engine.begin() as conn:
            res = conn.execute(
                collectors.update()
                .where(collectors.c.tenant_id == tenant_id, collectors.c.collector_id == collector_id)
                .values(last_seen=_utcnow())
            )
            if res.rowcount == 0:
                conn.execute(insert(collectors).values(tenant_id=tenant_id, collector_id=collector_id, last_seen=_utcnow()))

    def fleet(self, tenant_id: str, stale_after_s: int) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(collectors).where(collectors.c.tenant_id == tenant_id)).mappings().all()
        now = _utcnow()
        out = []
        for r in rows:
            age = (now - r["last_seen"]).total_seconds()
            if age > stale_after_s:
                state, reason = "Poor", f"no data or heartbeat for {int(age)}s (limit {stale_after_s}s)"
            else:
                state, reason = "Good", "reporting"
            out.append(
                {
                    "collector_id": r["collector_id"],
                    "state": state,
                    "state_reason": reason,
                    "last_seen_utc": r["last_seen"].replace(tzinfo=timezone.utc).isoformat(),
                    "version": r["version"],
                    "buffer_depth": r["buffer_depth"],
                }
            )
        return out

    def metrics(self, tenant_id: str, name: str | None, source: str | None, start: datetime | None, end: datetime | None, limit: int = 1000) -> list[dict]:
        q = select(events).where(events.c.tenant_id == tenant_id, events.c.kind == "metric")
        if name:
            q = q.where(events.c.name == name)
        if source:
            q = q.where(events.c.source_id == source)
        if start:
            q = q.where(events.c.event_ts >= start)
        if end:
            q = q.where(events.c.event_ts <= end)
        q = q.order_by(events.c.event_ts).limit(limit)  # event time, never arrival time
        with self.engine.connect() as conn:
            rows = conn.execute(q).mappings().all()
        return [
            {
                "event_ts_utc": r["event_ts"].replace(tzinfo=timezone.utc).isoformat(),
                "source_id": r["source_id"],
                "name": r["name"],
                "value": r["value"],
                "unit": r["unit"],
            }
            for r in rows
        ]

    def count_events(self, tenant_id: str) -> int:
        from sqlalchemy import func

        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(events).where(events.c.tenant_id == tenant_id)).scalar_one())
