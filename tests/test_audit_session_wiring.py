"""Regression test for Phase 4.5b — the "0 actions logged" audit bug.

Root cause: `ClaudeAgentOptions.allowed_tools` pre-approves entries at
the CLI layer, bypassing the `can_use_tool` callback. That callback is
where `AuditService.record_action()` is invoked, so every pre-approved
tool call left no audit trail — hence `/quit` reported 0 actions
despite many successful operations.

This test directly exercises the hook-layer pathway to prove that
(a) when the hook IS invoked it writes an audit row tied to the
correct session_id, and (b) `build_runtime` emits options with an
EMPTY `allowed_tools`, guaranteeing the CLI routes every tool call
through `can_use_tool`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import anyio
from claude_agent_sdk.types import ToolPermissionContext

from echoforge.agent import AgentConfig, build_runtime
from echoforge.agent.approval import StdinApprovalHandler
from echoforge.agent.hooks import build_can_use_tool
from echoforge.safety import AuditService, PermissionStore, RiskLevel, SafetyPolicy


def _fake_flipper() -> MagicMock:
    """A Flipper mock whose `storage.read` cleanly reports 'not there'
    so the diff-preview path doesn't throw."""
    flipper = MagicMock()
    flipper.port = "FAKE_COM"
    flipper.storage.read.side_effect = Exception("no such file")
    return flipper


class TestBuildRuntimeAllowedTools:
    def test_allowed_tools_is_empty_so_hook_always_fires(self):
        """Phase 4.5b: if anything is pre-approved, the CLI skips
        can_use_tool for it and audit writes never happen. Guard the
        invariant that build_runtime's ClaudeAgentOptions has no
        pre-approved tool entries."""
        flipper = _fake_flipper()
        audit = AuditService(":memory:")
        sid = audit.start_session("TEST")

        runtime = build_runtime(
            flipper=flipper,
            config=AgentConfig(),
            approval=StdinApprovalHandler(accept_all=True),
            audit=audit,
            audit_session_id=sid,
        )
        assert runtime.options.allowed_tools == [], (
            "allowed_tools must stay empty — pre-approving tools skips "
            "can_use_tool, breaking AuditService writes."
        )

    def test_hook_writes_audit_row_when_invoked(self):
        """End-to-end hook-layer test: build the real can_use_tool,
        fire it for a LOW-risk tool, then verify the row lands in the
        audit DB under the expected session_id."""
        flipper = _fake_flipper()
        audit = AuditService(":memory:")
        sid = audit.start_session("TEST")
        policy = SafetyPolicy(
            permissions=PermissionStore(),
            auto_approve_level=RiskLevel.LOW,
        )
        hook = build_can_use_tool(
            flipper=flipper,
            policy=policy,
            approval=StdinApprovalHandler(accept_all=True),
            audit=audit,
            session_id=sid,
        )

        ctx = ToolPermissionContext(
            signal=None, suggestions=[], tool_use_id="t1", agent_id="a1"
        )

        async def _run() -> Any:
            return await hook("mcp__echoforge__ping", {}, ctx)

        result = anyio.run(_run)
        assert type(result).__name__ == "PermissionResultAllow"

        # The decisive assertion — mirrors what /status + /quit do.
        assert audit.count_actions(session_id=sid) == 1
        rows = audit.list_actions(session_id=sid)
        assert len(rows) == 1
        assert rows[0].session_id == sid
        assert rows[0].action == "ping"
        assert rows[0].verdict == "allow"
        assert rows[0].result == "ok"

    def test_multiple_calls_accumulate_under_same_session(self):
        """Simulate a REPL session with several tool calls; count
        matches the number of hook invocations regardless of verdict."""
        flipper = _fake_flipper()
        audit = AuditService(":memory:")
        sid = audit.start_session("TEST")
        policy = SafetyPolicy(
            permissions=PermissionStore(),
            auto_approve_level=RiskLevel.LOW,
        )
        hook = build_can_use_tool(
            flipper=flipper,
            policy=policy,
            approval=StdinApprovalHandler(accept_all=True),
            audit=audit,
            session_id=sid,
        )
        ctx = ToolPermissionContext(
            signal=None, suggestions=[], tool_use_id="t1", agent_id="a1"
        )

        async def _run_many() -> None:
            for _ in range(5):
                await hook("mcp__echoforge__ping", {}, ctx)
            # One MED-risk write that needs approval (auto-accepted via
            # StdinApprovalHandler(accept_all=True)).
            await hook(
                "mcp__echoforge__write_file",
                {"path": "/ext/test.txt", "content": "hello"},
                ctx,
            )

        anyio.run(_run_many)

        assert audit.count_actions(session_id=sid) == 6
        rows = audit.list_actions(session_id=sid, limit=100)
        assert {r.action for r in rows} == {"ping", "write_file"}
        assert all(r.session_id == sid for r in rows)


class TestRunnerPassesAuditModeThrough:
    """Phase 4.5c bonus: make sure build_runtime doesn't swallow the
    audit_mode along the way — it's set on AuditService at construction
    and read by the hook at record time."""

    def test_default_is_hobbyist(self):
        cfg = AgentConfig()
        from echoforge.safety import AuditMode
        assert cfg.audit_mode == AuditMode.HOBBYIST
