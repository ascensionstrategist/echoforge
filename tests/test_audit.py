"""Unit tests for the AuditService (in-memory SQLite)."""

from __future__ import annotations

import threading

import pytest

from echoforge.safety.audit import AuditService


@pytest.fixture
def audit() -> AuditService:
    svc = AuditService(":memory:")
    yield svc
    svc.close()


class TestSessions:
    def test_start_and_end(self, audit):
        sid = audit.start_session("FLIP_TEST")
        assert isinstance(sid, str) and len(sid) > 0
        audit.end_session(sid)  # no error

    def test_session_ctx_manager(self, audit):
        with audit.session("FLIP_CTX") as sid:
            assert isinstance(sid, str)
            # Can record inside the session
            audit.record_action(
                session_id=sid,
                action="list_directory",
                args={"path": "/ext"},
                risk_level="LOW",
                verdict="allow",
            )


class TestRecording:
    def test_record_roundtrip(self, audit):
        sid = audit.start_session()
        rid = audit.record_action(
            session_id=sid,
            action="read_file",
            args={"path": "/ext/subghz/x.sub"},
            risk_level="LOW",
            verdict="allow",
            reason="auto-approved",
        )
        audit.record_result(rid, result="ok", payload={"bytes_read": 123})

        records = audit.list_actions(session_id=sid)
        assert len(records) == 1
        rec = records[0]
        assert rec.id == rid
        assert rec.action == "read_file"
        assert rec.args == {"path": "/ext/subghz/x.sub"}
        assert rec.risk_level == "LOW"
        assert rec.verdict == "allow"
        assert rec.reason == "auto-approved"
        assert rec.result == "ok"
        assert rec.result_payload == {"bytes_read": 123}
        assert rec.error is None

    def test_error_result(self, audit):
        sid = audit.start_session()
        rid = audit.record_action(
            session_id=sid, action="delete",
            args={"path": "/ext/x"}, risk_level="HIGH", verdict="require_approval",
        )
        audit.record_result(rid, result="error", error="ERROR_STORAGE_NOT_EXIST")
        rec = audit.list_actions(session_id=sid)[0]
        assert rec.result == "error"
        assert rec.error == "ERROR_STORAGE_NOT_EXIST"


class TestFiltering:
    def test_filter_by_action(self, audit):
        sid = audit.start_session()
        for a in ("read_file", "write_file", "read_file", "delete"):
            audit.record_action(
                session_id=sid, action=a, args={}, risk_level="MEDIUM", verdict="allow",
            )
        reads = audit.list_actions(action="read_file")
        assert len(reads) == 2
        assert all(r.action == "read_file" for r in reads)

    def test_count_actions(self, audit):
        sid = audit.start_session()
        for _ in range(5):
            audit.record_action(
                session_id=sid, action="ping", args={}, risk_level="LOW", verdict="allow",
            )
        assert audit.count_actions(session_id=sid) == 5

    def test_limit(self, audit):
        sid = audit.start_session()
        for _ in range(20):
            audit.record_action(
                session_id=sid, action="ping", args={}, risk_level="LOW", verdict="allow",
            )
        assert len(audit.list_actions(session_id=sid, limit=7)) == 7


class TestConcurrency:
    def test_threaded_writes_do_not_lose_records(self, audit):
        sid = audit.start_session()
        N = 50
        T = 5

        def worker(tid: int):
            for i in range(N):
                audit.record_action(
                    session_id=sid, action=f"t{tid}", args={"i": i},
                    risk_level="LOW", verdict="allow",
                )

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(T)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert audit.count_actions(session_id=sid) == N * T


class TestNonJsonSerializableArgs:
    def test_bytes_args_do_not_crash(self, audit):
        sid = audit.start_session()
        rid = audit.record_action(
            session_id=sid, action="write_file",
            args={"path": "/ext/x", "content": b"\x00\x01\x02"},
            risk_level="MEDIUM", verdict="require_approval",
        )
        # Should be recorded successfully (bytes fall back to str() via default=).
        rec = audit.list_actions()[0]
        assert rec.id == rid
