"""Local store: raw records (secrets visible, never leave), outbox (buffer) and egress log.

Everything here lives inside the customer environment.

Limits (E7). A flood or a long outage must not fill the disk, so growth is capped where data is written, not only
by a timer:
  * raw rows            capped by row count (`raw_max_rows`) and by live database size (`max_db_bytes`)
  * pending payloads    capped (`outbox_max_pending`); when full the OLDEST pending payloads are dropped first
                        (stale telemetry is worth less than fresh), the loss is counted and later reported
  * age                 raw records and delivered/rejected outbox rows are deleted after their retention period
                        (`apply_retention`, run on a schedule). Undelivered payloads are never deleted by age.
Every drop and purge is counted in the `meta` table so data loss is visible (GET /local/retention) and never silent.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path

def canonical(payload: dict) -> bytes:
    """The exact bytes of one payload as it appears inside a delivery batch (sorted keys, no spaces)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_of(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


# Enforce write-time caps every N inserts: cheap, and bounds how far a flood can overshoot a cap.
_RAW_CHECK_EVERY = 100
_ENQUEUE_CHECK_EVERY = 50


class LocalStore:
    def __init__(
        self,
        data_dir: Path | str,
        raw_max_rows: int = 500_000,
        outbox_max_pending: int = 100_000,
        max_db_bytes: int = 1 << 30,
    ):
        self.raw_max_rows = max(1, int(raw_max_rows))
        self.outbox_max_pending = max(1, int(outbox_max_pending))
        self.max_db_bytes = max(1 << 20, int(max_db_bytes))
        path = Path(data_dir)
        self.in_memory = str(data_dir) == ":memory:"
        if not self.in_memory:
            path.mkdir(parents=True, exist_ok=True)
            self.db_path = str(path / "collector.db")
        else:
            self.db_path = ":memory:"
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._raw_since_check = 0
        self._enqueue_since_check = 0
        with self._lock:
            if not self.in_memory:
                # WAL + NORMAL: far fewer disk syncs per insert, and still safe against a crash of the process.
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    received_at REAL NOT NULL,
                    text TEXT NOT NULL,
                    redactions TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    payload_id TEXT PRIMARY KEY,
                    raw_id INTEGER,
                    body TEXT NOT NULL,
                    redactions TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    sent_at REAL
                );
                CREATE INDEX IF NOT EXISTS outbox_status ON outbox(status, next_attempt_at);
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value REAL NOT NULL DEFAULT 0
                );
                """
            )
            # One payload now summarizes many raw records, so keep all their ids (older databases lack this column).
            cols = {r["name"] for r in self._db.execute("PRAGMA table_info(outbox)")}
            if "raw_ids" not in cols:
                self._db.execute("ALTER TABLE outbox ADD COLUMN raw_ids TEXT NOT NULL DEFAULT '[]'")
            if "digest" not in cols:  # SHA-256 of the payload's canonical bytes, fixed when it is queued
                self._db.execute("ALTER TABLE outbox ADD COLUMN digest TEXT")
            self._db.commit()

    # ---- counters that survive restarts ----
    def _meta_add(self, key: str, n: float) -> None:
        self._db.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = value + excluded.value",
            (key, n),
        )

    def _meta_set(self, key: str, value: float) -> None:
        self._db.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value)
        )

    def _meta_get(self, key: str) -> float:
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return float(row["value"]) if row else 0.0

    # ---- size accounting ----
    def _live_bytes(self) -> int:
        """Bytes of live data (pages in use). Unlike the file size this drops after deletes, so caps do not thrash."""
        page_size = self._db.execute("PRAGMA page_size").fetchone()[0]
        pages = self._db.execute("PRAGMA page_count").fetchone()[0]
        free = self._db.execute("PRAGMA freelist_count").fetchone()[0]
        return int((pages - free) * page_size)

    def disk_bytes(self) -> int:
        """Everything this store occupies on disk: the database and its write-ahead log."""
        if self.in_memory:
            return 0
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(self.db_path + suffix)
            except OSError:
                pass
        return total

    # ---- write-time caps (callers hold the lock) ----
    def _enforce_raw_limits_locked(self) -> int:
        trimmed = 0
        cur = self._db.execute(
            "DELETE FROM raw WHERE id <= (SELECT MAX(id) FROM raw) - ?", (self.raw_max_rows,)
        )  # ids only grow, so this keeps the newest `raw_max_rows`
        trimmed += max(0, cur.rowcount)
        live = self._live_bytes()
        if live > self.max_db_bytes:
            total = int(self._db.execute("SELECT COUNT(*) FROM raw").fetchone()[0])
            if total:
                avg = live / total
                n = min(total, math.ceil((live - 0.8 * self.max_db_bytes) / max(avg, 1.0)))
                cur = self._db.execute("DELETE FROM raw WHERE id IN (SELECT id FROM raw ORDER BY id LIMIT ?)", (n,))
                trimmed += max(0, cur.rowcount)
        if trimmed:
            self._meta_add("trimmed_raw_total", trimmed)
        return trimmed

    def _cap_pending_locked(self) -> int:
        pending = int(self._db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0])
        excess = pending - self.outbox_max_pending
        if excess <= 0:
            return 0
        cur = self._db.execute(
            "DELETE FROM outbox WHERE payload_id IN ("
            "SELECT payload_id FROM outbox WHERE status='pending' ORDER BY created_at, rowid LIMIT ?)",
            (excess,),
        )
        dropped = max(0, cur.rowcount)
        self._meta_add("dropped_overflow_total", dropped)
        self._meta_add("dropped_overflow_unreported", dropped)
        return dropped

    # ---- raw (local only) ----
    def add_raw(self, text: str, redactions: list[str]) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO raw(received_at, text, redactions) VALUES (?,?,?)",
                (time.time(), text, json.dumps(redactions)),
            )
            self._raw_since_check += 1
            if self._raw_since_check >= _RAW_CHECK_EVERY:
                self._raw_since_check = 0
                self._enforce_raw_limits_locked()
            self._db.commit()
            return int(cur.lastrowid)

    def recent_raw(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM raw ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "redactions": json.loads(r["redactions"])} for r in rows]

    def purge_raw(self, older_than_s: int) -> int:
        """Delete raw records older than `older_than_s` seconds. Returns how many."""
        with self._lock:
            cur = self._db.execute("DELETE FROM raw WHERE received_at < ?", (time.time() - older_than_s,))
            self._db.commit()
            return cur.rowcount

    # ---- scheduled retention ----
    def apply_retention(self, raw_max_age_s: float, outbox_max_age_s: float, now: float | None = None) -> dict:
        """Delete expired data and re-check the caps. Run on a timer; safe to call at any time.

        Raw records are deleted after `raw_max_age_s`. Delivered or rejected outbox rows (the transfer record) are
        deleted after `outbox_max_age_s`. Pending payloads are never deleted by age, only by the overflow cap.
        """
        now = time.time() if now is None else now
        with self._lock:
            raw_purged = self._db.execute("DELETE FROM raw WHERE received_at < ?", (now - raw_max_age_s,)).rowcount
            outbox_purged = self._db.execute(
                "DELETE FROM outbox WHERE status IN ('sent', 'rejected') AND COALESCE(sent_at, created_at) < ?",
                (now - outbox_max_age_s,),
            ).rowcount
            trimmed = self._enforce_raw_limits_locked()
            dropped = self._cap_pending_locked()
            self._meta_add("purged_raw_total", max(0, raw_purged))
            self._meta_add("purged_outbox_total", max(0, outbox_purged))
            self._meta_set("last_retention_run", now)
            self._db.commit()
            if not self.in_memory:
                try:
                    self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # keep the write-ahead log from lingering
                except sqlite3.Error:
                    pass
        return {"raw_purged": max(0, raw_purged), "outbox_purged": max(0, outbox_purged), "raw_trimmed": trimmed, "pending_dropped": dropped}

    def take_unreported_drops(self) -> int:
        """Payloads dropped to overflow since the last report. Returns the number and resets it, so each loss is
        reported to the platform once."""
        with self._lock:
            n = int(self._meta_get("dropped_overflow_unreported"))
            if n:
                self._meta_set("dropped_overflow_unreported", 0)
                self._db.commit()
            return n

    def retention_status(self) -> dict:
        with self._lock:
            raw_rows = int(self._db.execute("SELECT COUNT(*) FROM raw").fetchone()[0])
            oldest = self._db.execute("SELECT MIN(received_at) FROM raw").fetchone()[0]
            counts = {r["status"]: r["c"] for r in self._db.execute("SELECT status, COUNT(*) c FROM outbox GROUP BY status")}
            totals = {
                k: int(self._meta_get(k))
                for k in ("purged_raw_total", "purged_outbox_total", "trimmed_raw_total", "dropped_overflow_total", "dropped_overflow_unreported")
            }
            last_run = self._meta_get("last_retention_run")
            live = self._live_bytes()
        return {
            "usage": {
                "raw_rows": raw_rows,
                "oldest_raw_age_s": round(time.time() - oldest, 1) if oldest else None,
                "outbox": counts,
                "live_bytes": live,
                "disk_bytes": self.disk_bytes(),
            },
            "limits": {"raw_max_rows": self.raw_max_rows, "outbox_max_pending": self.outbox_max_pending, "max_db_bytes": self.max_db_bytes},
            "totals": totals,
            "last_retention_run_epoch": last_run or None,
        }

    # ---- outbox / egress ----
    def enqueue(self, payload: dict, raw_ids: "list[int] | int | None", redactions: list[str]) -> None:
        ids = [raw_ids] if isinstance(raw_ids, int) else list(raw_ids or [])
        with self._lock:
            self._db.execute(
                "INSERT INTO outbox(payload_id, raw_id, raw_ids, body, redactions, created_at, digest) VALUES (?,?,?,?,?,?,?)",
                (
                    payload["payload_id"],
                    ids[0] if ids else None,
                    json.dumps(ids),
                    json.dumps(payload, sort_keys=True),
                    json.dumps(sorted(set(redactions))),
                    time.time(),
                    digest_of(payload),
                ),
            )
            self._enqueue_since_check += 1
            if self._enqueue_since_check >= _ENQUEUE_CHECK_EVERY:
                self._enqueue_since_check = 0
                self._cap_pending_locked()
            self._db.commit()

    def pending(self, limit: int) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload_id, body FROM outbox WHERE status='pending' AND next_attempt_at <= ? "
                "ORDER BY created_at LIMIT ?",
                (time.time(), limit),
            ).fetchall()
        return [json.loads(r["body"]) for r in rows]

    def pending_rows(self, limit: int) -> list[tuple[dict, str | None]]:
        """Like pending(), with the digest fixed at queue time so the sender can prove it sends what was queued."""
        with self._lock:
            rows = self._db.execute(
                "SELECT body, digest FROM outbox WHERE status='pending' AND next_attempt_at <= ? ORDER BY created_at LIMIT ?",
                (time.time(), limit),
            ).fetchall()
        return [(json.loads(r["body"]), r["digest"]) for r in rows]

    def pending_info(self) -> dict:
        """What is waiting: how many, how long the oldest has waited, and when the next retry is due."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) c, MIN(created_at) oldest, MIN(next_attempt_at) next_try, MAX(attempts) max_attempts "
                "FROM outbox WHERE status='pending'"
            ).fetchone()
        now = time.time()
        return {
            "pending": int(row["c"]),
            "oldest_pending_age_s": round(now - row["oldest"], 1) if row["oldest"] else None,
            "next_retry_in_s": round(max(0.0, row["next_try"] - now), 1) if row["c"] and row["next_try"] and row["next_try"] > now else 0.0 if row["c"] else None,
            "max_attempts": int(row["max_attempts"] or 0),
        }

    def mark_sent(self, payload_ids: list[str]) -> None:
        with self._lock:
            self._db.executemany(
                "UPDATE outbox SET status='sent', sent_at=? WHERE payload_id=?",
                [(time.time(), pid) for pid in payload_ids],
            )
            self._db.commit()

    def mark_rejected(self, payload_id: str, reason: str) -> None:
        """Permanently refused by the SaaS: stop retrying, keep the record for the operator."""
        with self._lock:
            self._db.execute("UPDATE outbox SET status='rejected', sent_at=? WHERE payload_id=?", (time.time(), payload_id))
            self._db.commit()

    def mark_failed(self, payload_ids: list[str]) -> None:
        """Exponential backoff per payload, capped at 30 s."""
        with self._lock:
            now = time.time()
            for pid in payload_ids:
                row = self._db.execute("SELECT attempts FROM outbox WHERE payload_id=?", (pid,)).fetchone()
                attempts = (row["attempts"] if row else 0) + 1
                self._db.execute(
                    "UPDATE outbox SET attempts=?, next_attempt_at=? WHERE payload_id=?",
                    (attempts, now + min(30, 2**attempts), pid),
                )
            self._db.commit()

    def egress_one(self, payload_id: str) -> dict | None:
        """One payload exactly as queued, with the raw record ids and redactions behind it."""
        with self._lock:
            r = self._db.execute(
                "SELECT payload_id, raw_id, raw_ids, body, redactions, status, attempts, created_at, sent_at, digest "
                "FROM outbox WHERE payload_id=?",
                (payload_id,),
            ).fetchone()
        if r is None:
            return None
        return {
            "payload_id": r["payload_id"],
            "raw_ids": json.loads(r["raw_ids"]),
            "status": r["status"],
            "attempts": r["attempts"],
            "created_at": r["created_at"],
            "sent_at": r["sent_at"],
            "redactions_applied": json.loads(r["redactions"]),
            "payload": json.loads(r["body"]),
            "digest": r["digest"] or digest_of(json.loads(r["body"])),
        }

    def raw_by_ids(self, ids: list[int]) -> list[dict]:
        """Raw records by id (local only). Records past retention are simply absent."""
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM raw WHERE id IN ({marks}) ORDER BY id", list(ids)).fetchall()
        return [{**dict(r), "redactions": json.loads(r["redactions"])} for r in rows]

    def depth(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0])

    def counts(self) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT status, COUNT(*) c FROM outbox GROUP BY status").fetchall()
        return {r["status"]: r["c"] for r in rows}

    def recent_egress(self, limit: int = 50) -> list[dict]:
        """Exactly what was queued to leave, newest first, with the redactions applied upstream."""
        with self._lock:
            rows = self._db.execute(
                "SELECT payload_id, raw_id, raw_ids, body, redactions, status, attempts, created_at, sent_at, digest "
                "FROM outbox ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "payload_id": r["payload_id"],
                "raw_id": r["raw_id"],
                "raw_ids": json.loads(r["raw_ids"]),
                "status": r["status"],
                "attempts": r["attempts"],
                "created_at": r["created_at"],
                "sent_at": r["sent_at"],
                "redactions_applied": json.loads(r["redactions"]),
                "payload": json.loads(r["body"]),
                "digest": r["digest"] or digest_of(json.loads(r["body"])),
            }
            for r in rows
        ]
