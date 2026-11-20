"""Local store: raw records (secrets visible, never leave), outbox (buffer) and egress log.

Everything here lives inside the customer environment.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class LocalStore:
    def __init__(self, data_dir: Path | str):
        path = Path(data_dir)
        if str(data_dir) != ":memory:":
            path.mkdir(parents=True, exist_ok=True)
            db_path = str(path / "collector.db")
        else:
            db_path = ":memory:"
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
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
                """
            )

    # ---- raw (local only) ----
    def add_raw(self, text: str, redactions: list[str]) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO raw(received_at, text, redactions) VALUES (?,?,?)",
                (time.time(), text, json.dumps(redactions)),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def recent_raw(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM raw ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "redactions": json.loads(r["redactions"])} for r in rows]

    def purge_raw(self, older_than_s: int) -> int:
        """Local retention control."""
        with self._lock:
            cur = self._db.execute("DELETE FROM raw WHERE received_at < ?", (time.time() - older_than_s,))
            self._db.commit()
            return cur.rowcount

    # ---- outbox / egress ----
    def enqueue(self, payload: dict, raw_id: int | None, redactions: list[str]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO outbox(payload_id, raw_id, body, redactions, created_at) VALUES (?,?,?,?,?)",
                (payload["payload_id"], raw_id, json.dumps(payload, sort_keys=True), json.dumps(redactions), time.time()),
            )
            self._db.commit()

    def pending(self, limit: int) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload_id, body FROM outbox WHERE status='pending' AND next_attempt_at <= ? "
                "ORDER BY created_at LIMIT ?",
                (time.time(), limit),
            ).fetchall()
        return [json.loads(r["body"]) for r in rows]

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
                "SELECT payload_id, raw_id, body, redactions, status, attempts, created_at, sent_at "
                "FROM outbox ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "payload_id": r["payload_id"],
                "raw_id": r["raw_id"],
                "status": r["status"],
                "attempts": r["attempts"],
                "created_at": r["created_at"],
                "sent_at": r["sent_at"],
                "redactions_applied": json.loads(r["redactions"]),
                "payload": json.loads(r["body"]),
            }
            for r in rows
        ]
