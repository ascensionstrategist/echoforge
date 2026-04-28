"""
Pre-tool-use safety gate.

Builds a `can_use_tool` callback that plugs into
`ClaudeAgentOptions.can_use_tool`. Every proposed tool call is routed
through SafetyPolicy; the approval handler handles MEDIUM/HIGH prompts;
the audit service logs the decision.

The callback is async because the SDK requires it, and because the
approval handler may be slow (user reading a diff).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from echoforge.agent.approval import ApprovalHandler
from echoforge.agent.tools import TOOL_TO_RISK_ACTION
from echoforge.flipper import Flipper
from echoforge.safety import AuditMode, AuditService, SafetyPolicy
from echoforge.transport import RpcError

log = logging.getLogger(__name__)


PermissionResult = PermissionResultAllow | PermissionResultDeny
CanUseToolFn = Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResult],
]


# Phase 4.5c — tools whose primary-payload bytes should be captured into
# the audit `content_blob` column under OPERATOR mode. Each entry names
# the args field holding the verbatim payload. These are the only write
# actions where full-fidelity reproduction is a client-report
# requirement; pure filesystem operations (rename, copy, delete) and
# non-write actions don't need content capture.
_OPERATOR_CONTENT_FIELDS: dict[str, str] = {
    "write_file": "content",
    "payload_badusb_create": "script_text",
}


def _extract_operator_content(
    short_name: str, tool_input: dict[str, Any]
) -> Optional[bytes]:
    """Return the verbatim payload bytes for OPERATOR-mode audit capture.

    Only write-path actions with a known payload field are captured.
    Returns None for reads, physical actuations, and writes whose content
    isn't naturally a single blob (e.g. imports that just rename files).
    """
    field = _OPERATOR_CONTENT_FIELDS.get(short_name)
    if field is None:
        return None
    value = tool_input.get(field)
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        # Honor an explicit `encoding='hex'` when write_file uses it
        # (matches the tool body in tools.py so audit bytes match what
        # gets written to the Flipper).
        if short_name == "write_file" and tool_input.get("encoding") == "hex":
            try:
                return bytes.fromhex(value.replace(" ", ""))
            except ValueError:
                # Malformed hex — fall through to utf-8 so the operator
                # still sees *something* in the audit log; the tool
                # itself will raise the real error.
                pass
        return value.encode("utf-8")
    return None


def _resolve_diff_target_path(
    short_name: str, tool_input: dict[str, Any]
) -> Optional[str]:
    """Return the Flipper-side path whose current content should be read
    to produce a DiffSummary for `short_name`.

    Returns None for tools that don't need a diff (reads / physical
    actuations) or when the args don't carry enough info to synthesise
    a target. For the four Phase 6 MED-write actions, we must
    synthesise the target from args exactly the way the tool will — the
    tool layer owns filename composition (see tools_payload.py).

    Coupling note: the path-synthesis logic is duplicated between this
    helper and the tool body. This is deliberate; the alternative (a
    shared synthesis function) would force a circular import between
    agent/hooks.py and agent/tools_payload.py. Kept DRY by sharing the
    kind-root constants with a comment that any change to tools_payload
    must be mirrored here.
    """
    if short_name == "write_file":
        path = tool_input.get("path")
        return path if isinstance(path, str) else None
    if short_name == "payload_badusb_create":
        name = tool_input.get("name")
        if not isinstance(name, str) or not name:
            return None
        fname = name if name.endswith(".txt") else f"{name}.txt"
        return f"/ext/badusb/{fname}"
    if short_name == "payload_subghz_retune":
        # F1: we intentionally diff against dest_path, NOT source_path.
        # A retune creates a NEW file at dest with header-swapped bytes; the
        # source capture is read-only. Resolving from dest gives the correct
        # "new file" preview (current_content=None when the dest doesn't exist
        # yet). Reading source would produce a nonsense diff of source-bytes
        # vs new-metadata, which is not what the operator needs to approve.
        dest_name = tool_input.get("dest_name")
        if not isinstance(dest_name, str) or not dest_name:
            return None
        dest_fname = dest_name if dest_name.endswith(".sub") else f"{dest_name}.sub"
        return f"/ext/subghz/{dest_fname}"
    if short_name == "payload_subghz_import_capture":
        dest_name = tool_input.get("dest_name")
        if not isinstance(dest_name, str) or not dest_name:
            return None
        dest_fname = dest_name if dest_name.endswith(".sub") else f"{dest_name}.sub"
        return f"/ext/subghz/{dest_fname}"
    if short_name == "payload_ir_import_capture":
        dest_name = tool_input.get("dest_name")
        if not isinstance(dest_name, str) or not dest_name:
            return None
        dest_fname = dest_name if dest_name.endswith(".ir") else f"{dest_name}.ir"
        return f"/ext/infrared/{dest_fname}"
    return None


def build_can_use_tool(
    *,
    flipper: Flipper,
    policy: SafetyPolicy,
    approval: ApprovalHandler,
    audit: Optional[AuditService] = None,
    session_id: Optional[str] = None,
) -> CanUseToolFn:
    """
    Construct the async `can_use_tool` callback for the SDK.

    Args:
        flipper: live Flipper facade (used to read current file contents
            when computing diffs for write_file approvals).
        policy: configured SafetyPolicy.
        approval: UI handler for MEDIUM/HIGH confirmations.
        audit: optional AuditService; if provided, every decision is logged.
        session_id: audit session id (ignored if `audit` is None).

    Only SDK MCP tools whose names start with the echoforge MCP prefix
    ("mcp__echoforge__") are gated — all built-in Claude Code tools are
    passed through unchanged (we neither register nor use them by default,
    but if the user enabled any, we don't interfere).
    """
    echoforge_prefix = "mcp__echoforge__"

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        # Normalize the name — SDK MCP tools come through as
        # "mcp__<server_name>__<tool_name>".
        short_name = tool_name.split("__")[-1] if tool_name.startswith(echoforge_prefix) else tool_name

        # Unknown tool — fail safe.
        action = TOOL_TO_RISK_ACTION.get(short_name)
        if action is None:
            deny_message = (
                f"tool {tool_name!r} is not a registered echoforge action; "
                "refusing as a safety precaution"
            )
            # Phase 4.5 review MEDIUM-1: unknown-tool rejections must be
            # audited. Silently dropping them creates a gap in the trail
            # the operator relies on for accountability (bug report,
            # prompt injection, or future refactor hitting this path).
            if audit is not None and session_id is not None:
                unknown_action_id = audit.record_action(
                    session_id=session_id,
                    action="unknown_tool",
                    args={"tool_name": tool_name, "tool_input": tool_input},
                    risk_level="BLOCKED",
                    verdict="block",
                    reason=deny_message,
                )
                audit.record_result(
                    unknown_action_id, result="denied", error=deny_message
                )
            return PermissionResultDeny(message=deny_message, interrupt=False)

        # For MED-write actions, try to fetch current content so the
        # diff shows meaningful context. If the file doesn't exist, that
        # fine — the policy handles new-file previews.
        #
        # Review C1 fix: the payload Forge MED-write actions
        # (payload_badusb_create, payload_subghz_retune,
        # payload_*_import_capture) also need current_content so
        # SafetyPolicy can emit a DiffSummary. For each, we resolve the
        # *target* path (synthesised from args) via
        # TOOL_PRIMARY_PATH_FIELD plus per-action logic.
        current_content: Optional[bytes] = None
        target_path = _resolve_diff_target_path(short_name, tool_input)
        if target_path is not None:
            try:
                current_content = flipper.storage.read(target_path)
            except RpcError as exc:
                if exc.status_name != "ERROR_STORAGE_NOT_EXIST":
                    log.warning(
                        "safety hook: couldn't read %s for diff: %s",
                        target_path,
                        exc,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "safety hook: couldn't read %s for diff: %s", target_path, exc
                )

        decision = policy.assess(action, tool_input, current_content=current_content)

        # Audit record — created regardless of verdict.
        # Phase 4.5c: in OPERATOR mode we also capture the verbatim
        # payload bytes for known write actions. HOBBYIST mode ignores
        # the blob (AuditService enforces this defensively as well).
        action_id: Optional[int] = None
        if audit is not None and session_id is not None:
            content_blob: Optional[bytes] = None
            if audit.audit_mode == AuditMode.OPERATOR:
                content_blob = _extract_operator_content(short_name, tool_input)
            action_id = audit.record_action(
                session_id=session_id,
                action=action,
                args=tool_input,
                risk_level=str(decision.risk_level),
                verdict=decision.verdict,
                reason=decision.reason,
                content_blob=content_blob,
            )

        # Dispatch by verdict.
        if decision.verdict == "block":
            if action_id is not None and audit is not None:
                audit.record_result(action_id, result="denied", error=decision.reason)
            return PermissionResultDeny(message=decision.reason, interrupt=False)

        if decision.verdict == "allow":
            if action_id is not None and audit is not None:
                audit.record_result(action_id, result="ok", payload={"auto_approved": True})
            return PermissionResultAllow()

        # require_approval — ask the user.
        result = await approval.prompt(
            tool_name=tool_name,
            args=tool_input,
            decision=decision,
        )
        if audit is not None and action_id is not None:
            if result.approved:
                audit.record_result(action_id, result="ok", payload={"user_approved": True})
            else:
                audit.record_result(action_id, result="denied", error=result.reason or "user declined")

        if not result.approved:
            return PermissionResultDeny(
                message=result.reason or "user declined",
                interrupt=False,
            )
        return PermissionResultAllow()

    return can_use_tool
