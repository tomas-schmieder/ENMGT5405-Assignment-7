"""Case metadata store (SQLite) used by the dashboard listing.

The authoritative case state lives in the LangGraph checkpointer. This table
is a small, query-friendly summary that the service refreshes after every
graph run, so the dashboard can list and filter cases without loading every
checkpoint.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    taxpayer TEXT,
    filing_status TEXT,
    pending_kind TEXT,
    pending_event_id TEXT,
    pending_reason TEXT,
    pending_summary TEXT,
    draft_version INTEGER,
    refund TEXT,
    owed TEXT,
    llm_mode TEXT,
    error TEXT,
    extra TEXT
);
"""


class CaseStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def upsert(self, row: dict) -> None:
        cols = ["case_id", "created_at", "updated_at", "status", "taxpayer", "filing_status", "pending_kind",
                "pending_event_id", "pending_reason", "pending_summary", "draft_version", "refund", "owed",
                "llm_mode", "error", "extra"]
        values = [row.get(c) if c != "extra" else json.dumps(row.get("extra") or {}) for c in cols]
        sql = (f"INSERT INTO cases ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
               f"ON CONFLICT(case_id) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "case_id"
                                                                 and c != "created_at"))
        with self._lock:
            self._conn.execute(sql, values)
            self._conn.commit()

    def get(self, case_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            if status:
                rows = self._conn.execute("SELECT * FROM cases WHERE status = ? ORDER BY updated_at DESC", (status,))
            else:
                rows = self._conn.execute("SELECT * FROM cases ORDER BY updated_at DESC")
            return [self._row(r) for r in rows.fetchall()]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["extra"] = json.loads(d.get("extra") or "{}")
        return d
