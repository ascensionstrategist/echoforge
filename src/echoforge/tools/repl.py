"""
Interactive REPL for echoforge.

A persistent session with Claude over your Flipper Zero — Claude remembers
conversational context across turns, so you can have a real dialogue:

    you > what's on my SD card?
    claude > (lists it)
    you > anything that looks out of place?
    claude > (without re-listing, pulls from memory: the RPi boot files)

Slash commands:
    /help          — show this help
    /quit, /q      — exit
    /clear         — reset the conversation (new Claude session)
    /status        — show Flipper + audit counts
    /audit [N]     — show the last N audit entries (default 10)
    /grants        — list active permission grants
    /grant <pat>   — grant temporary permission (default 1h)
    /revoke <pat>  — revoke a grant
    /multiline     — toggle multi-line input mode (end with '.' on its own line)
    /auto <level>  — change auto-approve level: low / medium / high / none

Usage:
    python -m echoforge.tools.repl                 # auto-detect Flipper
    python -m echoforge.tools.repl COM7            # force a port
    python -m echoforge.tools.repl --accept-all    # dev-mode: approve everything
    python -m echoforge.tools.repl --audit audit.db  # persist audit log to file
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from echoforge.agent import (
    AgentConfig,
    StdinApprovalHandler,
    EchoforgeAgent,
)
from echoforge.flipper import Flipper, FlipperConnectionError
from echoforge.safety import AuditMode, RiskLevel


console = Console()


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

def _print_entry(entry: dict[str, Any]) -> None:
    """Render one transcript entry with modest color coding."""
    role = entry["role"]
    typ = entry["type"]

    if typ == "text" and role == "assistant":
        # Claude prose
        console.print(entry["text"], style="bright_white")

    elif typ == "text" and role == "user":
        # Echoed user text (rare — we print our own prompt)
        console.print(entry["text"], style="dim")

    elif typ == "thinking":
        # Extended thinking blocks — dim, italic
        text = entry["text"].rstrip()
        if text:
            console.print(f"[dim italic]∙ {text}[/]")

    elif typ == "tool_use":
        name = entry["name"].rsplit("__", 1)[-1]
        args = entry["input"]
        pretty = _fmt_tool_args(args)
        console.print(f"[cyan]▸ {name}[/][dim]({pretty})[/]")

    elif typ == "tool_result":
        content = entry["content"].rstrip()
        if not content:
            return
        if entry.get("is_error"):
            console.print(f"  [red]✗ {_shorten(content)}[/]")
        else:
            console.print(f"  [green]✓[/] {_shorten(content, 800)}", style="dim")


def _fmt_tool_args(args: dict[str, Any]) -> str:
    items: list[str] = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 60:
            items.append(f"{k}='{v[:60]}...'")
        else:
            items.append(f"{k}={v!r}")
    return ", ".join(items)


def _shorten(s: str, max_chars: int = 500) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 30] + f"\n... [{len(s) - max_chars + 30} more chars]"


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

SLASH_HELP = """[bold]echoforge REPL commands[/]

  [cyan]/help[/]              show this help
  [cyan]/quit[/], [cyan]/q[/]          exit
  [cyan]/clear[/]             reset conversation (new Claude session)
  [cyan]/status[/]            Flipper + audit summary
  [cyan]/audit[/] [[yellow]N[/]]         show last N audit rows (default 10)
  [cyan]/grants[/]            list active permission grants
  [cyan]/grant[/] [yellow]<pat>[/] [[yellow]hours[/]]  grant temp permission (default 1h)
  [cyan]/revoke[/] [yellow]<pat>[/]     revoke a grant
  [cyan]/multiline[/]         toggle multi-line input (end input with '.' alone)
  [cyan]/auto[/] [yellow]<level>[/]     auto-approve level: low / medium / high / none
"""


class ReplSession:
    """Owns the live EchoforgeAgent and the interactive loop."""

    def __init__(
        self,
        *,
        flipper: Flipper,
        config: AgentConfig,
        accept_all: bool,
    ):
        self._flipper = flipper
        self._config = config
        self._approval = StdinApprovalHandler(accept_all=accept_all)
        self._agent: Optional[EchoforgeAgent] = None
        self._multiline = False
        self._turn_count = 0

    async def __aenter__(self) -> "ReplSession":
        await self._spin_up_agent()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._agent is not None:
            await self._agent.__aexit__(None, None, None)

    async def _spin_up_agent(self) -> None:
        self._agent = EchoforgeAgent(
            flipper=self._flipper,
            config=self._config,
            approval=self._approval,
        )
        await self._agent.__aenter__()

    async def _restart_agent(self) -> None:
        """Tear down and reopen the agent — clears Claude's conversation history."""
        if self._agent is not None:
            await self._agent.__aexit__(None, None, None)
        await self._spin_up_agent()

    async def run(self) -> None:
        _print_banner(self._flipper)

        loop = asyncio.get_running_loop()
        while True:
            try:
                prompt_text = await loop.run_in_executor(None, self._read_input)
            except (EOFError, KeyboardInterrupt):
                console.print()  # clean newline
                break

            if prompt_text is None:
                # Empty line — just redraw prompt
                continue

            if prompt_text.startswith("/"):
                keep_going = await self._handle_slash(prompt_text)
                if not keep_going:
                    break
                continue

            await self._send_turn(prompt_text)

        await self._teardown_message()

    # -- input ------------------------------------------------------------

    def _read_input(self) -> Optional[str]:
        """Blocking readline — runs in a thread so asyncio stays responsive."""
        try:
            if self._multiline:
                console.print("[bold magenta]you ›[/] [dim](multi-line; '.' alone to send)[/]")
                lines: list[str] = []
                while True:
                    raw = input("… ")
                    if raw.strip() == ".":
                        break
                    lines.append(raw)
                text = "\n".join(lines).strip()
            else:
                raw = input("you › ")
                text = raw.strip()
        except EOFError:
            raise
        return text or None

    # -- turns ------------------------------------------------------------

    async def _send_turn(self, prompt: str) -> None:
        if self._agent is None:
            return
        self._turn_count += 1
        t0 = time.perf_counter()
        try:
            async for entry in self._agent.send(prompt):
                _print_entry(entry)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]‼ agent error:[/] {type(exc).__name__}: {exc}")
        dt = time.perf_counter() - t0
        console.print(f"[dim]  ↳ turn {self._turn_count} · {dt:.1f}s[/]")
        console.print()

    # -- slash commands ---------------------------------------------------

    async def _handle_slash(self, line: str) -> bool:
        """Return False if the user wants to exit."""
        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("/quit", "/q", "/exit"):
            return False
        if cmd == "/help":
            console.print(SLASH_HELP)
            return True
        if cmd == "/clear":
            console.print("[yellow]clearing conversation history[/]")
            await self._restart_agent()
            self._turn_count = 0
            return True
        if cmd == "/status":
            self._cmd_status()
            return True
        if cmd == "/audit":
            n = int(args[0]) if args else 10
            self._cmd_audit(n)
            return True
        if cmd == "/grants":
            self._cmd_grants()
            return True
        if cmd == "/grant":
            if len(args) < 1:
                console.print("[red]usage: /grant <pattern> [hours][/]")
                return True
            hours = float(args[1]) if len(args) > 1 else 1.0
            self._cmd_grant(args[0], hours)
            return True
        if cmd == "/revoke":
            if len(args) < 1:
                console.print("[red]usage: /revoke <pattern>[/]")
                return True
            self._cmd_revoke(args[0])
            return True
        if cmd == "/multiline":
            self._multiline = not self._multiline
            console.print(f"[yellow]multi-line input: {'ON' if self._multiline else 'OFF'}[/]")
            return True
        if cmd == "/auto":
            if len(args) < 1:
                console.print("[red]usage: /auto <low|medium|high|none>[/]")
                return True
            self._cmd_auto(args[0])
            return True
        console.print(f"[red]unknown command: {cmd}[/] (/help for list)")
        return True

    # -- slash impls ------------------------------------------------------

    def _cmd_status(self) -> None:
        if self._agent is None:
            console.print("[red]no active agent[/]")
            return
        audit = self._agent.audit
        session_id = self._agent.session_id
        total = audit.count_actions(session_id=session_id)
        by_verdict = {"allow": 0, "require_approval": 0, "block": 0}
        for r in audit.list_actions(session_id=session_id, limit=1000):
            by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
        console.print(
            Panel.fit(
                Text.from_markup(
                    f"[bold]port[/]        {self._flipper.port}\n"
                    f"[bold]turns[/]       {self._turn_count}\n"
                    f"[bold]actions[/]     {total} "
                    f"([green]allow {by_verdict['allow']}[/] / "
                    f"[yellow]approval {by_verdict['require_approval']}[/] / "
                    f"[red]block {by_verdict['block']}[/])\n"
                    f"[bold]auto-approve[/] {self._config.auto_approve_level.name}\n"
                ),
                title="echoforge status",
            )
        )

    def _cmd_audit(self, n: int) -> None:
        if self._agent is None:
            return
        records = self._agent.audit.list_actions(
            session_id=self._agent.session_id, limit=n
        )
        if not records:
            console.print("[dim](no audit entries yet)[/]")
            return
        for r in records:
            ts = time.strftime("%H:%M:%S", time.localtime(r.ts))
            verdict_color = {
                "allow": "green", "require_approval": "yellow", "block": "red",
            }.get(r.verdict, "white")
            result_bit = f" [{r.result}]" if r.result else ""
            console.print(
                f"[dim]{ts}[/] [{verdict_color}]{r.verdict:>16}[/] "
                f"{r.risk_level:<8} {r.action}{result_bit}"
            )

    def _cmd_grants(self) -> None:
        policy = _policy_from(self._agent)
        if policy is None:
            return
        grants = policy.permissions.active_grants()
        if not grants:
            console.print("[dim](no active grants)[/]")
            return
        now = time.time()
        for g in grants:
            remaining_s = int(g.expires_at - now)
            console.print(
                f"  [cyan]{g.pattern:<30}[/] expires in {remaining_s // 60}m{remaining_s % 60:02d}s  "
                f"[dim]{g.reason}[/]"
            )

    def _cmd_grant(self, pattern: str, hours: float) -> None:
        policy = _policy_from(self._agent)
        if policy is None:
            return
        policy.permissions.grant(pattern, duration_s=hours * 3600, reason="REPL /grant")
        console.print(f"[green]granted[/] {pattern} for {hours}h")

    def _cmd_revoke(self, pattern: str) -> None:
        policy = _policy_from(self._agent)
        if policy is None:
            return
        removed = policy.permissions.revoke(pattern)
        if removed:
            console.print(f"[green]revoked[/] {pattern}")
        else:
            console.print(f"[dim]no grant matching {pattern}[/]")

    def _cmd_auto(self, level_name: str) -> None:
        mapping = {
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "med": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH,
            "none": None,
            "off": None,
        }
        if level_name.lower() not in mapping:
            console.print(f"[red]unknown level {level_name!r}[/]; try low / medium / high / none")
            return
        new_level = mapping[level_name.lower()]
        self._config.auto_approve_level = new_level if new_level else RiskLevel.LOW
        console.print(
            f"[yellow]auto-approve: {level_name.upper()}[/] "
            f"(restart session for this to apply)"
        )
        console.print("  tip: run /clear to restart with the new setting")

    # -- lifecycle --------------------------------------------------------

    async def _teardown_message(self) -> None:
        if self._agent is None:
            return
        total = self._agent.audit.count_actions(session_id=self._agent.session_id)
        console.print(f"[dim]session ended. {self._turn_count} turns, {total} actions logged.[/]")


def _policy_from(agent: Optional[EchoforgeAgent]):
    """Expose the live SafetyPolicy from the agent (set by build_runtime)."""
    return agent.policy if agent is not None else None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _print_banner(flipper: Flipper) -> None:
    try:
        info = flipper.system.device_info()
    except TimeoutError:
        # Agent spin-up can hold the link idle long enough for the RPC
        # session to go stale before the 15s keepalive tick fires.
        flipper.reconnect()
        info = flipper.system.device_info()
    banner = Text.from_markup(
        f"[bold bright_magenta]echoforge[/] connected to "
        f"[cyan]{info.hardware_name}[/] on [cyan]{flipper.port}[/] "
        f"([dim]{info.firmware_branch}@{info.firmware_commit}[/])\n"
        f"[dim]type /help for commands, /quit to exit[/]"
    )
    console.print(Panel(banner, border_style="bright_magenta", padding=(0, 2)))


async def _main(
    port: Optional[str],
    *,
    accept_all: bool,
    audit_db: Optional[Path],
    audit_mode: AuditMode,
) -> int:
    try:
        cm = Flipper.connect(port=port)
    except FlipperConnectionError as exc:
        console.print(f"[red]✗ {exc}[/]")
        return 1

    with cm as flipper:
        config = AgentConfig(
            auto_approve_level=RiskLevel.LOW,
            audit_db_path=audit_db,
            audit_mode=audit_mode,
        )
        async with ReplSession(
            flipper=flipper, config=config, accept_all=accept_all
        ) as session:
            await session.run()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", default=None, help="COM port (auto-detect if omitted)")
    parser.add_argument("--accept-all", action="store_true",
                        help="dev mode: auto-approve every tool call (dangerous)")
    parser.add_argument("--audit", type=Path, default=None,
                        help="path to persist the SQLite audit log (default: in-memory)")
    parser.add_argument(
        "--audit-mode",
        choices=[m.value for m in AuditMode],
        default=AuditMode.HOBBYIST.value,
        help=(
            "audit granularity: 'hobbyist' (default) logs hashes only; "
            "'operator' captures full payload-file bytes for client reports. "
            "Operator mode makes the audit DB sensitive — protect it."
        ),
    )
    ns = parser.parse_args()
    try:
        return asyncio.run(
            _main(
                ns.port,
                accept_all=ns.accept_all,
                audit_db=ns.audit,
                audit_mode=AuditMode(ns.audit_mode),
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
