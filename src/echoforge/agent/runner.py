"""
echoforge agent runner.

Glues together:
  - live Flipper facade (phase 2)
  - SafetyPolicy + PermissionStore + AuditService (phase 3)
  - Claude Agent SDK (phase 4): SYSTEM_PROMPT, MCP tool server, can_use_tool
    hook, approval handler

Exposes two entry points:
  - `run_single_turn(prompt, ...)` — one user message, streams Claude's
    response, returns the final transcript. Simple for smoke tests.
  - `EchoforgeAgent` — persistent session for REPL-style interaction.

Claude model defaults to the fast Sonnet 4.6 via the CLI's bundled config.
Override via the `model=` argument or CLAUDE_MODEL env var.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
    UserMessage,
    create_sdk_mcp_server,
    query,
)

from echoforge.agent.approval import ApprovalHandler, StdinApprovalHandler
from echoforge.agent.hooks import build_can_use_tool
from echoforge.agent.prompts import SYSTEM_PROMPT
from echoforge.agent.tools import build_flipper_tools
from echoforge.agent.tools_payload import build_payload_tools
from echoforge.flipper import Flipper
from echoforge.safety import AuditMode, AuditService, PermissionStore, RiskLevel, SafetyPolicy

log = logging.getLogger(__name__)


DEFAULT_MCP_SERVER_NAME = "echoforge"
DEFAULT_MAX_TURNS = 20


@dataclass
class AgentConfig:
    """Runtime configuration for the agent loop."""
    model: Optional[str] = None
    auto_approve_level: RiskLevel = RiskLevel.LOW
    max_turns: int = DEFAULT_MAX_TURNS
    audit_db_path: Optional[Path] = None
    # Phase 4.5c: HOBBYIST stores content hashes only; OPERATOR captures
    # full payload-file bytes in the audit DB for client-report fidelity.
    # Default is HOBBYIST — operator mode is an explicit opt-in.
    audit_mode: AuditMode = AuditMode.HOBBYIST
    permission_store_path: Optional[Path] = None
    permission_mode: str = "default"  # passed to ClaudeAgentOptions


# ---------------------------------------------------------------------------
# Options builder
# ---------------------------------------------------------------------------

@dataclass
class AgentRuntime:
    """Bundle of live runtime objects built from config. Kept so callers
    (REPL, TUI) can access the SafetyPolicy and PermissionStore to offer
    `/grants` and `/revoke` without reimplementing them."""
    options: ClaudeAgentOptions
    policy: SafetyPolicy


def build_runtime(
    *,
    flipper: Flipper,
    config: AgentConfig,
    approval: ApprovalHandler,
    audit: AuditService,
    audit_session_id: str,
) -> AgentRuntime:
    """Compose ClaudeAgentOptions + SafetyPolicy. Policy is returned so
    the UI layer can mutate permissions at runtime."""
    permissions = PermissionStore(store_path=config.permission_store_path)
    policy = SafetyPolicy(
        permissions=permissions,
        auto_approve_level=config.auto_approve_level,
    )

    flipper_tools = build_flipper_tools(flipper)
    payload_tools = build_payload_tools(flipper)
    all_tools = [*flipper_tools, *payload_tools]
    mcp_server = create_sdk_mcp_server(
        name=DEFAULT_MCP_SERVER_NAME,
        version="0.1.0",
        tools=all_tools,
    )

    can_use_tool = build_can_use_tool(
        flipper=flipper,
        policy=policy,
        approval=approval,
        audit=audit,
        session_id=audit_session_id,
    )

    # Phase 4.5b audit-wiring fix:
    #
    # We MUST NOT pre-populate `allowed_tools` with our echoforge MCP
    # tools. The Claude Code CLI treats anything in `--allowedTools` as
    # already-approved and SKIPS the `can_use_tool` callback for those
    # tools. That exact shortcut is why every REPL `/quit` was printing
    # "0 actions logged" despite many successful tool calls — the hook
    # that writes to the AuditService was never fired.
    #
    # Leaving `allowed_tools` empty forces the CLI to route EVERY tool
    # call through `can_use_tool`, which is where SafetyPolicy assessment
    # AND AuditService writes live.
    options = ClaudeAgentOptions(
        model=config.model,
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={DEFAULT_MCP_SERVER_NAME: mcp_server},
        allowed_tools=[],
        disallowed_tools=[],
        can_use_tool=can_use_tool,
        max_turns=config.max_turns,
        permission_mode=config.permission_mode,  # type: ignore[arg-type]
    )
    return AgentRuntime(options=options, policy=policy)


def build_options(
    *,
    flipper: Flipper,
    config: AgentConfig,
    approval: ApprovalHandler,
    audit: AuditService,
    audit_session_id: str,
) -> ClaudeAgentOptions:
    """Back-compat wrapper for call sites that only need the options."""
    return build_runtime(
        flipper=flipper,
        config=config,
        approval=approval,
        audit=audit,
        audit_session_id=audit_session_id,
    ).options


# ---------------------------------------------------------------------------
# Single-turn helper
# ---------------------------------------------------------------------------

async def _single_prompt_stream(prompt: str):
    """Yield one user message in the SDK streaming format.

    Required when `options.can_use_tool` is set — the SDK only enables the
    permission callback in streaming-input mode. Shape:
        {"type": "user", "message": {"role": "user", "content": "..."}}
    """
    yield {"type": "user", "message": {"role": "user", "content": prompt}}


async def run_single_turn(
    prompt: str,
    *,
    flipper: Flipper,
    config: Optional[AgentConfig] = None,
    approval: Optional[ApprovalHandler] = None,
) -> list[dict]:
    """
    Send one user message and stream Claude's response until the agent stops.

    Returns a structured transcript: each list item is a dict with keys
    `role` ('user'|'assistant'|'tool'), `type`, and `text`/`data`.

    Useful for smoke tests and scripted single-shot queries. For
    interactive use, prefer `EchoforgeAgent`.
    """
    config = config or AgentConfig()
    approval = approval or StdinApprovalHandler()

    audit = AuditService(
        config.audit_db_path or ":memory:",
        audit_mode=config.audit_mode,
    )
    transcript: list[dict] = []
    try:
        with audit.session(device_name=flipper.port) as sid:
            options = build_options(
                flipper=flipper,
                config=config,
                approval=approval,
                audit=audit,
                audit_session_id=sid,
            )
            async for msg in query(prompt=_single_prompt_stream(prompt), options=options):
                for entry in _render_message(msg):
                    transcript.append(entry)
    finally:
        audit.close()
    return transcript


# ---------------------------------------------------------------------------
# Persistent agent
# ---------------------------------------------------------------------------

class EchoforgeAgent:
    """Stateful conversation — call `send(prompt)` repeatedly."""

    def __init__(
        self,
        *,
        flipper: Flipper,
        config: Optional[AgentConfig] = None,
        approval: Optional[ApprovalHandler] = None,
    ):
        self._flipper = flipper
        self._config = config or AgentConfig()
        self._approval = approval or StdinApprovalHandler()
        self._audit = AuditService(
            self._config.audit_db_path or ":memory:",
            audit_mode=self._config.audit_mode,
        )
        self._session_id = self._audit.start_session(device_name=flipper.port)
        runtime = build_runtime(
            flipper=flipper,
            config=self._config,
            approval=self._approval,
            audit=self._audit,
            audit_session_id=self._session_id,
        )
        self._options = runtime.options
        self.policy = runtime.policy
        self._client = ClaudeSDKClient(options=self._options)

    async def __aenter__(self) -> "EchoforgeAgent":
        await self._client.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        try:
            await self._client.disconnect()
        finally:
            self._audit.end_session(self._session_id)
            self._audit.close()

    @property
    def audit(self) -> AuditService:
        return self._audit

    @property
    def session_id(self) -> str:
        return self._session_id

    async def send(self, prompt: str) -> AsyncIterator[dict]:
        """Send a user message; yield rendered transcript entries as they arrive."""
        await self._client.query(prompt)
        async for msg in self._client.receive_response():
            for entry in _render_message(msg):
                yield entry


# ---------------------------------------------------------------------------
# Transcript rendering
# ---------------------------------------------------------------------------

def _render_message(msg: object) -> list[dict]:
    """Turn one SDK message into zero-or-more transcript entries."""
    out: list[dict] = []
    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextBlock):
                out.append({"role": "assistant", "type": "text", "text": block.text})
            elif isinstance(block, ThinkingBlock):
                out.append({"role": "assistant", "type": "thinking", "text": block.thinking})
            elif isinstance(block, ToolUseBlock):
                out.append({
                    "role": "assistant",
                    "type": "tool_use",
                    "name": block.name,
                    "input": block.input,
                })
            elif isinstance(block, ToolResultBlock):
                # Sometimes embedded in assistant messages for re-reads
                out.append({
                    "role": "assistant",
                    "type": "tool_result_echo",
                    "content": _extract_text(block.content),
                })
    elif isinstance(msg, UserMessage):
        for block in getattr(msg, "content", []) or []:
            if isinstance(block, ToolResultBlock):
                out.append({
                    "role": "tool",
                    "type": "tool_result",
                    "content": _extract_text(block.content),
                    "is_error": getattr(block, "is_error", False),
                })
            elif isinstance(block, TextBlock):
                out.append({"role": "user", "type": "text", "text": block.text})
    return out


def _extract_text(content: object) -> str:
    """Best-effort flatten of MCP content blocks to a single string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)
