"""echoforge agent — Claude Agent SDK integration."""

from echoforge.agent.approval import (
    ApprovalDecision,
    ApprovalHandler,
    StdinApprovalHandler,
)
from echoforge.agent.hooks import build_can_use_tool
from echoforge.agent.prompts import SYSTEM_PROMPT
from echoforge.agent.runner import (
    AgentConfig,
    AgentRuntime,
    EchoforgeAgent,
    build_runtime,
    run_single_turn,
)
from echoforge.agent.tools import TOOL_TO_RISK_ACTION, build_flipper_tools

__all__ = [
    "AgentConfig",
    "AgentRuntime",
    "ApprovalDecision",
    "ApprovalHandler",
    "StdinApprovalHandler",
    "SYSTEM_PROMPT",
    "TOOL_TO_RISK_ACTION",
    "EchoforgeAgent",
    "build_can_use_tool",
    "build_flipper_tools",
    "build_runtime",
    "run_single_turn",
]
