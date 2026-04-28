"""
User approval UI for MEDIUM/HIGH tool calls.

Abstract `ApprovalHandler` protocol — the CLI runner uses
`StdinApprovalHandler`, the TUI in Phase 5 will supply a Textual-based
one. Both produce the same `ApprovalDecision`.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Protocol

from echoforge.safety import Decision, DiffSummary, RiskLevel


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    reason: str = ""   # shown back to Claude if denied


class ApprovalHandler(Protocol):
    async def prompt(
        self,
        *,
        tool_name: str,
        args: dict,
        decision: Decision,
    ) -> ApprovalDecision: ...


class StdinApprovalHandler:
    """Prompts on stdin. Suitable for CLI / smoke tests. Runs the blocking
    input() inside a thread so the async loop isn't blocked."""

    def __init__(self, *, accept_all: bool = False):
        """`accept_all=True` is a dev-mode bypass (smoke tests / auto-yes)."""
        self._accept_all = accept_all

    async def prompt(
        self,
        *,
        tool_name: str,
        args: dict,
        decision: Decision,
    ) -> ApprovalDecision:
        if self._accept_all:
            return ApprovalDecision(approved=True, reason="accept_all mode")

        header = _format_header(tool_name, args, decision)
        sys.stderr.write(header)
        sys.stderr.flush()

        if decision.requires_hold:
            # HIGH risk — require explicit "HOLD" confirmation string.
            # (The TUI version will use hold-to-confirm; stdin uses the
            # keyword as a speed bump.)
            answer = (await _ainput("type HOLD to confirm, anything else to cancel: ")).strip()
            if answer == "HOLD":
                return ApprovalDecision(approved=True)
            return ApprovalDecision(approved=False, reason="user declined HIGH-risk op")

        # MEDIUM risk — simple y/N.
        answer = (await _ainput("approve? [y/N]: ")).strip().lower()
        if answer in {"y", "yes"}:
            return ApprovalDecision(approved=True)
        return ApprovalDecision(approved=False, reason="user declined")


def _format_header(tool_name: str, args: dict, decision: Decision) -> str:
    """Render a textual approval prompt."""
    lines = [
        "",
        "=" * 72,
        f"APPROVAL NEEDED — {decision.risk_level}",
        f"tool:   {tool_name}",
        f"reason: {decision.reason}",
    ]
    if args:
        # Truncate long 'content' fields so a 4KB paste doesn't scroll forever.
        preview_args = {}
        for k, v in args.items():
            if isinstance(v, str) and len(v) > 200:
                preview_args[k] = f"{v[:200]!r}... ({len(v)} chars total)"
            else:
                preview_args[k] = v
        lines.append(f"args:   {preview_args}")
    if decision.diff is not None:
        lines.append("")
        lines.append(_format_diff(decision.diff))
    lines.append("=" * 72)
    lines.append("")
    return "\n".join(lines)


def _format_diff(diff: DiffSummary) -> str:
    header = (
        f"— diff preview — {diff.path} "
        f"({'new' if diff.is_new else 'update'}, "
        f"{'binary' if diff.is_binary else f'+{diff.lines_added} -{diff.lines_removed} lines'}"
        f", size {diff.size_delta:+d} B)"
    )
    return f"{header}\n{diff.diff_text}"


async def _ainput(prompt: str) -> str:
    """Run blocking input() in a thread so asyncio loop stays responsive."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))
