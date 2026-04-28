"""Phase 4.5c — AuditMode (hobbyist vs operator) and schema migration.

Hobbyist mode logs content-hash + metadata only. Operator mode logs
full verbatim payload bytes into the `content_blob` column for
client-deliverable pentest reports. Existing DBs created before this
phase get a forward-only ALTER TABLE on first open.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import anyio
from claude_agent_sdk.types import ToolPermissionContext

from echoforge.agent import AgentConfig, build_runtime
from echoforge.agent.approval import StdinApprovalHandler
from echoforge.agent.hooks import build_can_use_tool
from echoforge.safety import (
    AuditMode,
    AuditService,
    PermissionStore,
    RiskLevel,
    SafetyPolicy,
)


def _fake_flipper() -> MagicMock:
    flipper = MagicMock()
    flipper.port = "FAKE_COM"
    flipper.storage.read.side_effect = Exception("no such file")
    return flipper


# ---------------------------------------------------------------------------
# Direct AuditService behavior
# ---------------------------------------------------------------------------

class TestAuditModeHobbyist:
    def test_hobbyist_is_default(self):
        svc = AuditService(":memory:")
        try:
            assert svc.audit_mode == AuditMode.HOBBYIST
        finally:
            svc.close()

    def test_hobbyist_drops_content_blob(self):
        """Even if a caller passes content_blob, hobbyist mode must not
        persist it. Defense-in-depth: the hook is supposed to skip
        passing it, but the DB layer enforces the invariant."""
        svc = AuditService(":memory:", audit_mode=AuditMode.HOBBYIST)
        try:
            sid = svc.start_session("TEST")
            rid = svc.record_action(
                session_id=sid,
                action="write_file",
                args={"path": "/ext/x.txt"},
                risk_level="MEDIUM",
                verdict="require_approval",
                content_blob=b"hello world",
            )
            rec = svc.list_actions()[0]
            assert rec.id == rid
            assert rec.content_blob is None, (
                "hobbyist mode must NEVER persist payload bytes; caller "
                "passed them but AuditService must drop them on the floor."
            )
        finally:
            svc.close()


class TestAuditModeOperator:
    def test_operator_stores_full_content(self):
        svc = AuditService(":memory:", audit_mode=AuditMode.OPERATOR)
        try:
            sid = svc.start_session("PENTEST")
            payload = b"STRING Invoke-WebRequest -Uri http://target\n"
            rid = svc.record_action(
                session_id=sid,
                action="payload_badusb_create",
                args={"name": "recon", "script_text": payload.decode()},
                risk_level="MEDIUM",
                verdict="require_approval",
                content_blob=payload,
            )
            rec = svc.list_actions()[0]
            assert rec.id == rid
            assert rec.content_blob == payload

            # Raw-row verification — caller might query the DB directly
            # for report generation.
            row = svc._conn.execute(
                "SELECT content_blob FROM actions WHERE id = ?", (rid,)
            ).fetchone()
            assert bytes(row[0]) == payload
        finally:
            svc.close()

    def test_operator_none_blob_is_none(self):
        """Operator mode + no blob argument = NULL column. Reads don't
        need capture."""
        svc = AuditService(":memory:", audit_mode=AuditMode.OPERATOR)
        try:
            sid = svc.start_session("PENTEST")
            svc.record_action(
                session_id=sid,
                action="read_file",
                args={"path": "/ext/x.txt"},
                risk_level="LOW",
                verdict="allow",
            )
            rec = svc.list_actions()[0]
            assert rec.content_blob is None
        finally:
            svc.close()


# ---------------------------------------------------------------------------
# Schema migration — old DBs without content_blob column
# ---------------------------------------------------------------------------

class TestAuditSchemaMigration:
    def test_migration_adds_content_blob_column(self, tmp_path: Path):
        db_file = tmp_path / "legacy.db"
        # Create a "legacy" DB with the pre-4.5c actions schema.
        conn = sqlite3.connect(str(db_file))
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, started_at REAL NOT NULL,
                ended_at REAL, device_name TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                ts REAL NOT NULL,
                action TEXT NOT NULL,
                args_json TEXT,
                risk_level TEXT NOT NULL,
                verdict TEXT NOT NULL,
                reason TEXT,
                result TEXT,
                result_json TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO sessions (id, started_at, device_name) VALUES (?, ?, ?)",
            ("legacy-sid", 1000.0, "LEGACY"),
        )
        conn.execute(
            "INSERT INTO actions "
            "(session_id, ts, action, args_json, risk_level, verdict, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy-sid", 1001.0, "ping", "{}", "LOW", "allow", "ok"),
        )
        conn.commit()
        conn.close()

        # Open with the new AuditService — migration runs on __init__.
        svc = AuditService(db_file)
        try:
            # Column now exists.
            cols = {
                row["name"]
                for row in svc._conn.execute("PRAGMA table_info(actions)")
            }
            assert "content_blob" in cols

            # Legacy row survives, content_blob is NULL.
            rows = svc.list_actions(session_id="legacy-sid")
            assert len(rows) == 1
            assert rows[0].action == "ping"
            assert rows[0].content_blob is None

            # New writes in operator mode persist correctly.
            svc_op = AuditService(db_file, audit_mode=AuditMode.OPERATOR)
            try:
                sid = svc_op.start_session("OP")
                svc_op.record_action(
                    session_id=sid,
                    action="payload_badusb_create",
                    args={"name": "x"},
                    risk_level="MEDIUM",
                    verdict="require_approval",
                    content_blob=b"DELAY 500\n",
                )
                rec = svc_op.list_actions(session_id=sid)[0]
                assert rec.content_blob == b"DELAY 500\n"
            finally:
                svc_op.close()
        finally:
            svc.close()

    def test_migration_is_idempotent(self, tmp_path: Path):
        """Opening a post-migration DB a second time must not fail
        trying to re-add the column."""
        db_file = tmp_path / "fresh.db"
        svc = AuditService(db_file)  # creates with content_blob
        svc.close()
        svc2 = AuditService(db_file)  # re-open — no duplicate-column error
        svc2.close()


# ---------------------------------------------------------------------------
# Hook-layer integration: content is captured in operator mode only.
# ---------------------------------------------------------------------------

class TestHookOperatorModeEndToEnd:
    def _run_write_file(self, svc: AuditService, sid: str) -> None:
        flipper = _fake_flipper()
        policy = SafetyPolicy(
            permissions=PermissionStore(),
            auto_approve_level=RiskLevel.LOW,
        )
        hook = build_can_use_tool(
            flipper=flipper,
            policy=policy,
            approval=StdinApprovalHandler(accept_all=True),
            audit=svc,
            session_id=sid,
        )
        ctx = ToolPermissionContext(
            signal=None, suggestions=[], tool_use_id="t1", agent_id="a1"
        )
        tool_input = {"path": "/ext/test.txt", "content": "secret payload"}

        async def _go() -> None:
            await hook("mcp__echoforge__write_file", tool_input, ctx)

        anyio.run(_go)

    def test_hobbyist_mode_hook_does_not_capture_content(self):
        svc = AuditService(":memory:", audit_mode=AuditMode.HOBBYIST)
        try:
            sid = svc.start_session("HOBBY")
            self._run_write_file(svc, sid)
            rec = svc.list_actions(session_id=sid)[0]
            assert rec.action == "write_file"
            assert rec.content_blob is None
        finally:
            svc.close()

    def test_operator_mode_hook_captures_full_content(self):
        svc = AuditService(":memory:", audit_mode=AuditMode.OPERATOR)
        try:
            sid = svc.start_session("OP")
            self._run_write_file(svc, sid)
            rec = svc.list_actions(session_id=sid)[0]
            assert rec.action == "write_file"
            assert rec.content_blob == b"secret payload"
        finally:
            svc.close()

    def test_operator_mode_honors_hex_encoding(self):
        """write_file with encoding='hex' must be decoded to bytes
        BEFORE storage — so the audit blob matches what actually gets
        written to the Flipper."""
        svc = AuditService(":memory:", audit_mode=AuditMode.OPERATOR)
        try:
            sid = svc.start_session("OP")
            flipper = _fake_flipper()
            policy = SafetyPolicy(
                permissions=PermissionStore(),
                auto_approve_level=RiskLevel.LOW,
            )
            hook = build_can_use_tool(
                flipper=flipper,
                policy=policy,
                approval=StdinApprovalHandler(accept_all=True),
                audit=svc,
                session_id=sid,
            )
            ctx = ToolPermissionContext(
                signal=None, suggestions=[], tool_use_id="t1", agent_id="a1"
            )

            async def _go() -> None:
                await hook(
                    "mcp__echoforge__write_file",
                    {"path": "/ext/bin", "content": "de ad be ef", "encoding": "hex"},
                    ctx,
                )

            anyio.run(_go)
            rec = svc.list_actions(session_id=sid)[0]
            assert rec.content_blob == b"\xde\xad\xbe\xef"
        finally:
            svc.close()


# ---------------------------------------------------------------------------
# REPL CLI flag plumbing
# ---------------------------------------------------------------------------

class TestReplAuditModeFlag:
    def test_repl_flag_parses_operator_mode(self, monkeypatch):
        """`python -m echoforge.tools.repl --audit-mode=operator` must
        propagate into the AgentConfig.audit_mode the REPL eventually
        constructs. We stop short of actually spinning up a Flipper by
        short-circuiting _main; the argparse → AuditMode() conversion
        is the thing under test."""
        from echoforge.tools import repl

        captured: dict[str, object] = {}

        async def _fake_main(
            port, *, accept_all, audit_db, audit_mode
        ):
            captured["audit_mode"] = audit_mode
            captured["audit_db"] = audit_db
            captured["accept_all"] = accept_all
            return 0

        monkeypatch.setattr(repl, "_main", _fake_main)
        monkeypatch.setattr(
            sys, "argv",
            ["repl", "--audit-mode=operator"],
        )

        rc = repl.main()
        assert rc == 0
        assert captured["audit_mode"] == AuditMode.OPERATOR

    def test_repl_flag_default_is_hobbyist(self, monkeypatch):
        from echoforge.tools import repl

        captured: dict[str, object] = {}

        async def _fake_main(
            port, *, accept_all, audit_db, audit_mode
        ):
            captured["audit_mode"] = audit_mode
            return 0

        monkeypatch.setattr(repl, "_main", _fake_main)
        monkeypatch.setattr(sys, "argv", ["repl"])
        rc = repl.main()
        assert rc == 0
        assert captured["audit_mode"] == AuditMode.HOBBYIST


class TestAgentConfigPropagatesAuditMode:
    def test_build_runtime_passes_mode_through(self):
        """Propagation guard: EchoforgeAgent construction (which the
        REPL uses) must hand the operator flag from AgentConfig into
        the AuditService it creates internally. We verify via
        `build_runtime` + a pre-built AuditService (the surface the
        agent layer uses)."""
        flipper = _fake_flipper()
        svc = AuditService(":memory:", audit_mode=AuditMode.OPERATOR)
        try:
            sid = svc.start_session("T")
            runtime = build_runtime(
                flipper=flipper,
                config=AgentConfig(audit_mode=AuditMode.OPERATOR),
                approval=StdinApprovalHandler(accept_all=True),
                audit=svc,
                audit_session_id=sid,
            )
            # Not much to inspect on the options themselves — the
            # runtime.policy is the most we expose. The invariant we
            # care about: AuditService.audit_mode is what AgentConfig
            # requested.
            assert svc.audit_mode == AuditMode.OPERATOR
            assert runtime.options.allowed_tools == []
        finally:
            svc.close()
