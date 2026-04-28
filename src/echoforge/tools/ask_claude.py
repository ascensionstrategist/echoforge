"""
Phase 4 end-to-end smoke test.

Wires the full stack together and asks Claude one question that should
trigger a tool call against the live Flipper.

Usage:
    python -m echoforge.tools.ask_claude
    python -m echoforge.tools.ask_claude "what's on my flipper's SD card?"
    python -m echoforge.tools.ask_claude --accept-all "flash the LED green briefly"

`--accept-all` skips the stdin approval step (useful for scripted tests).
Only do that for known-safe LOW-risk requests.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
from typing import Any

from echoforge.agent import AgentConfig, StdinApprovalHandler, run_single_turn
from echoforge.flipper import Flipper, FlipperConnectionError
from echoforge.safety import RiskLevel


DEFAULT_PROMPT = (
    "What's on my Flipper Zero's SD card? "
    "List the top-level entries under /ext — no need for a deep scan."
)


def _render_entry(entry: dict[str, Any]) -> str:
    role = entry["role"]
    typ = entry["type"]
    if typ == "text":
        body = entry["text"].rstrip()
        prefix = "claude" if role == "assistant" else "user"
        return f"[{prefix}] {body}"
    if typ == "thinking":
        return f"[thinking] {entry['text'].rstrip()}"
    if typ == "tool_use":
        name = entry["name"].split("__")[-1]
        args = entry["input"]
        pretty = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"[tool_use] {name}({pretty})"
    if typ == "tool_result":
        content = entry["content"].rstrip()
        tag = "tool_error" if entry.get("is_error") else "tool_result"
        return textwrap.indent(f"[{tag}]\n{content}", "    ")
    return f"[{role}/{typ}] {entry}"


async def _main(prompt: str, *, accept_all: bool) -> int:
    try:
        cm = Flipper.connect()
    except FlipperConnectionError as exc:
        print(f"[ask_claude] {exc}", file=sys.stderr)
        return 1

    with cm as f:
        print(f"[ask_claude] Flipper on {f.port} ready")
        print(f"[ask_claude] prompt: {prompt}\n")

        config = AgentConfig(auto_approve_level=RiskLevel.LOW)
        approval = StdinApprovalHandler(accept_all=accept_all)

        transcript = await run_single_turn(
            prompt,
            flipper=f,
            config=config,
            approval=approval,
        )
        for entry in transcript:
            print(_render_entry(entry))
            print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT,
                        help="user message to send (default: scan /ext)")
    parser.add_argument("--accept-all", action="store_true",
                        help="auto-approve MEDIUM/HIGH ops (dangerous; smoke tests only)")
    ns = parser.parse_args()
    return asyncio.run(_main(ns.prompt, accept_all=ns.accept_all))


if __name__ == "__main__":
    raise SystemExit(main())
