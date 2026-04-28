"""
SQLite-backed audit log.

Every AI-initiated action is written to this store alongside the risk
assessment, user decision (allow / require_approval / block), and final
result (success / denied / error). The schema is flat and query-friendly
so the TUI can render filtered timelines.

Stored fields:
  sessions(id, started_at, ended_at, device_name)
  actions(
    id, session_id, ts,
    action, args_json,
    risk_level, verdict, reason,
    result, result_json, error,
    content_blob            -- OPERATOR mode only; full payload bytes
  )

Thread-safe: sqlite3 connection wraps a mutex; each method takes the
lock. Writes go through a single connection (SQLite's own locking is
sufficient for this write volume).

**OPERATOR MODE SAFETY NOTE (Phase 4.5c):**
When `AuditMode.OPERATOR` is set, `record_action()` may be called with a
`content_blob` argument holding the full verbatim bytes of payload-file
writes (DuckyScript text, .sub body, .ir body). This is intentional and
by design — pentest engagement reports need "here's exactly what we
ran, here's what it did" fidelity. Full content is stored WITHOUT any
redaction or sanitization.

Consequence: the audit DB may contain sensitive bytes (credentials from
captured .sub files, target-network hints from DuckyScripts, client
secrets embedded in payloads). It is the OPERATOR's responsibility to
treat the DB as sensitive — store it at rest on an encrypted volume,
scrub it at end-of-engagement, don't ship it to third-party analytics.
echoforge does not ship with a built-in secret scrubber and will not —
that would defeat the point of OPERATOR mode.

Hobbyist mode (default) stores content-hash only (SHA-256) for privacy
and forward-compatibility with the DB-as-non-sensitive model.
"""

from __future__ import annotations

import enum
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    started_at  REAL NOT NULL,
    ended_at    REAL,
    device_name TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(id),
    ts           REAL NOT NULL,
    action       TEXT NOT NULL,
    args_json    TEXT,
    risk_level   TEXT NOT NULL,
    verdict      TEXT NOT NULL,
    reason       TEXT,
    result       TEXT,        -- 'ok' | 'denied' | 'error' | null (pending)
    result_json  TEXT,
    error        TEXT,
    content_blob BLOB         -- OPERATOR mode: full payload bytes; else NULL
);

CREATE INDEX IF NOT EXISTS ix_actions_session ON actions(session_id);
CREATE INDEX IF NOT EXISTS ix_actions_ts      ON actions(ts);
CREATE INDEX IF NOT EXISTS ix_actions_action  ON actions(action);
"""


# Forward-only migration: older DBs created before Phase 4.5c don't have
# `content_blob`. We detect its absence on connect and ALTER TABLE to
# add it; existing rows keep NULL (fine — HOBBYIST semantics).
_MIGRATION_ADD_CONTENT_BLOB = "ALTER TABLE actions ADD COLUMN content_blob BLOB"


class AuditMode(str, enum.Enum):
    """Audit-log granularity. Default HOBBYIST; operator opts in to OPERATOR.

    HOBBYIST:
        Log tool name, args, file path, content SHA-256 hash, timestamp,
        risk level, and approval outcome. Full payload bytes are NOT
        persisted. Safe to leave unencrypted; safe to share as "proof I
        didn't do anything destructive".

    OPERATOR:
        Everything in HOBBYIST plus a `content_blob` column holding the
        verbatim bytes of payload-file writes (DuckyScript .txt, .sub
        body, .ir body). Required for client-deliverable pentest reports
        where the engagement contract demands "here's exactly what we
        ran" fidelity. The DB becomes sensitive; operator is responsible
        for storage/transport security (see module docstring).
    """

    HOBBYIST = "hobbyist"
    OPERATOR = "operator"

    def __str__(self) -> str:  # enable `str(AuditMode.OPERATOR)` => 'operator'
        return self.value


@dataclass(frozen=True)
class ActionRecord:
    id: int
    session_id: str
    ts: float
    action: str
    args: Mapping[str, Any]
    risk_level: str
    verdict: str
    reason: str
    result: Optional[str]
    result_payload: Optional[Mapping[str, Any]]
    error: Optional[str]
    content_blob: Optional[bytes] = None


class AuditService:
    """SQLite-backed action log.

    Args:
        db_path: path to the SQLite DB, or ':memory:' for tests.
        audit_mode: HOBBYIST (default) stores hashes only; OPERATOR
            stores full payload-file content in the `content_blob`
            column. See module docstring for the sensitivity tradeoff.
    """

    def __init__(
        self,
        db_path: Path | str = ":memory:",
        *,
        audit_mode: AuditMode = AuditMode.HOBBYIST,
    ):
        self._db_path = str(db_path)
        self._audit_mode = audit_mode
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        # `check_same_thread=False` so multiple threads can share one
        # connection, coordinated via our own lock.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        # Forward-only migration for DBs created before Phase 4.5c — add
        # the content_blob column if it doesn't exist. `PRAGMA
        # table_info` is cheap and avoids ALTER-failure on replays.
        self._ensure_content_blob_column()
        self._lock = threading.Lock()

    @property
    def audit_mode(self) -> AuditMode:
        """Current audit granularity. Set at construction time; immutable."""
        return self._audit_mode

    def _ensure_content_blob_column(self) -> None:
        cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(actions)")}
        if "content_blob" not in cols:
            self._conn.execute(_MIGRATION_ADD_CONTENT_BLOB)

    # -- sessions ----------------------------------------------------------

    def start_session(self, device_name: str = "") -> str:
        sid = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, started_at, device_name) VALUES (?, ?, ?)",
                (sid, time.time(), device_name),
            )
        return sid

    def end_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                (time.time(), session_id),
            )

    # -- actions -----------------------------------------------------------

    def record_action(
        self,
        *,
        session_id: str,
        action: str,
        args: Mapping[str, Any],
        risk_level: str,
        verdict: str,
        reason: str = "",
        content_blob: Optional[bytes] = None,
    ) -> int:
        """Record the pre-execution entry. Returns the row id to update later.

        `content_blob` is persisted ONLY when `self.audit_mode ==
        AuditMode.OPERATOR`. In HOBBYIST mode the argument is silently
        dropped (it's the hook layer's job to not call with a blob when
        the mode is wrong, but we defensively enforce the invariant here
        too — the DB must never carry payload content under hobbyist).
        """
        blob_to_write: Optional[bytes] = None
        if content_blob is not None and self._audit_mode == AuditMode.OPERATOR:
            blob_to_write = bytes(content_blob)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO actions "
                "(session_id, ts, action, args_json, risk_level, verdict, reason, content_blob) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    time.time(),
                    action,
                    _safe_json(args),
                    str(risk_level),
                    str(verdict),
                    reason,
                    blob_to_write,
                ),
            )
            return int(cur.lastrowid)

    def record_result(
        self,
        action_id: int,
        *,
        result: str,                     # 'ok' | 'denied' | 'error'
        payload: Optional[Mapping[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE actions SET result = ?, result_json = ?, error = ? WHERE id = ?",
                (result, _safe_json(payload) if payload is not None else None, error, action_id),
            )

    # -- queries -----------------------------------------------------------

    def list_actions(
        self,
        *,
        session_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> list[ActionRecord]:
        q = "SELECT * FROM actions WHERE 1=1"
        params: list[Any] = []
        if session_id:
            q += " AND session_id = ?"
            params.append(session_id)
        if action:
            q += " AND action = ?"
            params.append(action)
        q += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = list(self._conn.execute(q, params))

        return [_row_to_record(r) for r in rows]

    def count_actions(self, *, session_id: Optional[str] = None) -> int:
        q = "SELECT COUNT(*) FROM actions"
        params: list[Any] = []
        if session_id:
            q += " WHERE session_id = ?"
            params.append(session_id)
        with self._lock:
            cur = self._conn.execute(q, params)
            return int(cur.fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def session(self, device_name: str = "") -> Iterator[str]:
        sid = self.start_session(device_name)
        try:
            yield sid
        finally:
            self.end_session(sid)


# -- helpers ----------------------------------------------------------------

def _safe_json(value: Any) -> str:
    """Serialize value to JSON, tolerating non-serializable bits by str()."""
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps({"_repr": repr(value)})


def _row_to_record(row: sqlite3.Row) -> ActionRecord:
    args = {}
    if row["args_json"]:
        try:
            args = json.loads(row["args_json"])
        except json.JSONDecodeError:
            pass
    payload = None
    if row["result_json"]:
        try:
            payload = json.loads(row["result_json"])
        except json.JSONDecodeError:
            pass
    # content_blob is optional — older DBs may not have the column even
    # after migration if the row was read via a stale cursor; sqlite3.Row
    # raises IndexError for missing columns, so guard defensively.
    blob: Optional[bytes] = None
    try:
        raw = row["content_blob"]
    except (IndexError, KeyError):
        raw = None
    if raw is not None:
        blob = bytes(raw)
    return ActionRecord(
        id=int(row["id"]),
        session_id=row["session_id"],
        ts=float(row["ts"]),
        action=row["action"],
        args=args,
        risk_level=row["risk_level"],
        verdict=row["verdict"],
        reason=row["reason"] or "",
        result=row["result"],
        result_payload=payload,
        error=row["error"],
        content_blob=blob,
    )
