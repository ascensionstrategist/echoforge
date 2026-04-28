"""
Safety policy — composes risk + permissions + diff into a single verdict.

Usage pattern for the Claude agent layer:

    policy = SafetyPolicy(auto_approve_level=RiskLevel.LOW)
    decision = policy.assess(
        action="write_file",
        args={"path": "/ext/subghz/garage.sub", "content": "..."},
        current_content=existing_bytes,   # None if file is new
    )
    if decision.verdict == "allow":
        # just execute
    elif decision.verdict == "require_approval":
        # show decision.risk_level + decision.diff to user, wait for OK
        # (hold-to-confirm if decision.requires_hold)
    elif decision.verdict == "block":
        # refuse and return decision.reason to the model
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Optional, Union

from echoforge.safety.diff import DiffSummary, summarize_write
from echoforge.safety.permissions import PermissionStore
from echoforge.safety.risk import RiskAssessor, RiskAssessment, RiskLevel


Verdict = Literal["allow", "require_approval", "block"]


# Actions for which `_build_diff` should attempt to produce a DiffSummary.
# DECISIONS.md §3: "All write paths emit a DiffSummary before approval".
# Each entry is (action_name, primary_path_field, new_content_resolver).
# For actions whose new content is already in `args` (write_file,
# badusb_create), the resolver is a simple key lookup. For actions that
# synthesise content (subghz_retune serialises a preview SubFile),
# the resolver falls back to a placeholder — the hooks layer is
# responsible for computing a real synthesised bytes when one is
# needed, and we honor it via `args["_preview_content"]` when present.
#
# We accept the slight coupling of knowing these action names here
# because the alternative — a pluggable diff strategy registry — is
# overkill for four actions and a Phase-6-scoped problem.
_DIFFABLE_ACTIONS: dict[str, str] = {
    "write_file": "path",
    "payload_badusb_create": "path",
    "payload_subghz_retune": "path",
    "payload_subghz_import_capture": "path",
    "payload_ir_import_capture": "path",
}


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    risk_level: RiskLevel
    reason: str
    diff: Optional[DiffSummary] = None
    requires_hold: bool = False            # True for HIGH → hold-to-confirm
    assessment: Optional[RiskAssessment] = None


class SafetyPolicy:
    """Coordinates risk, permissions, and diff preparation."""

    def __init__(
        self,
        *,
        risk: Optional[RiskAssessor] = None,
        permissions: Optional[PermissionStore] = None,
        auto_approve_level: Optional[RiskLevel] = RiskLevel.LOW,
    ):
        """
        Args:
            risk:
                RiskAssessor to use. Default: standard ruleset.
            permissions:
                PermissionStore. Default: in-memory, no persistence.
            auto_approve_level:
                Risk levels <= this are allowed without user approval. Set
                to `None` to require approval for everything (paranoid
                mode). Default: LOW.
        """
        self._risk = risk or RiskAssessor()
        self._perms = permissions or PermissionStore()
        self._auto_approve = auto_approve_level

    @property
    def permissions(self) -> PermissionStore:
        return self._perms

    @property
    def assessor(self) -> RiskAssessor:
        return self._risk

    # -- core entry point --------------------------------------------------

    def assess(
        self,
        action: str,
        args: Mapping[str, Any],
        *,
        current_content: Optional[Union[bytes, str]] = None,
    ) -> Decision:
        """
        Return the verdict for a proposed tool call.

        `current_content` is the existing contents of the target file for
        write actions, so we can compute a diff. Pass `None` if the file
        doesn't yet exist or the action isn't a write.
        """
        assessment = self._risk.assess(action, args)

        # 1. Blocked paths — check if any unlock covers them.
        if assessment.level == RiskLevel.BLOCKED:
            unlocked_all = all(
                self._perms.is_unlocked(p) for p in assessment.blocked_paths
            ) if assessment.blocked_paths else False

            if not unlocked_all:
                remaining = [
                    p for p in assessment.blocked_paths if not self._perms.is_unlocked(p)
                ]
                return Decision(
                    verdict="block",
                    risk_level=RiskLevel.BLOCKED,
                    reason=(
                        f"Path(s) in protected area and not unlocked: "
                        f"{', '.join(remaining)}. Use the permissions panel to "
                        f"grant temporary access."
                    ),
                    assessment=assessment,
                )
            # User has unlocked these paths — treat as HIGH (still confirm).
            return self._build_high(action, args, assessment, note="path unlocked")

        # 2. Auto-approve cheap reads if configured.
        if self._auto_approve is not None and assessment.level <= self._auto_approve:
            return Decision(
                verdict="allow",
                risk_level=assessment.level,
                reason=f"auto-approved at {assessment.level}",
                assessment=assessment,
            )

        # 3. Dispatch by level.
        if assessment.level == RiskLevel.LOW:
            return Decision(
                verdict="allow",
                risk_level=RiskLevel.LOW,
                reason=assessment.reason,
                assessment=assessment,
            )

        if assessment.level == RiskLevel.MEDIUM:
            diff = None
            if action in _DIFFABLE_ACTIONS:
                diff = self._build_diff(action, args, current_content)
            return Decision(
                verdict="require_approval",
                risk_level=RiskLevel.MEDIUM,
                reason=assessment.reason,
                diff=diff,
                assessment=assessment,
            )

        # HIGH
        return self._build_high(action, args, assessment)

    # -- helpers -----------------------------------------------------------

    def _build_high(
        self,
        action: str,
        args: Mapping[str, Any],
        assessment: RiskAssessment,
        *,
        note: str = "",
    ) -> Decision:
        reason = assessment.reason
        if note:
            reason = f"{reason} ({note})"
        return Decision(
            verdict="require_approval",
            risk_level=RiskLevel.HIGH,
            reason=reason,
            requires_hold=True,
            assessment=assessment,
        )

    def _build_diff(
        self,
        action: str,
        args: Mapping[str, Any],
        current_content: Optional[Union[bytes, str]],
    ) -> Optional[DiffSummary]:
        """Produce a DiffSummary for a MED-write action.

        Handles the five MED-write actions declared in `_DIFFABLE_ACTIONS`:

        * `write_file`               — raw content in args["content"].
        * `payload_badusb_create`    — DuckyScript source in
          args["script_text"]; target path synthesised from args["name"].
        * `payload_subghz_retune`    — synthesised SubFile-preview; we
          can't actually serialise here without the source bytes, so we
          fall back to a metadata-only diff describing the freq/preset
          change. If a caller (e.g. hooks.py) supplies a
          `_preview_content` override in args, that wins.
        * `payload_subghz_import_capture` / `payload_ir_import_capture` —
          a rename + sidecar-write. We diff the `rename from → to`
          intent as a one-line pseudo-diff (since we don't rewrite the
          file contents, just its path).

        Returns None only if we genuinely can't figure out a target
        path. Otherwise always returns a DiffSummary — the whole point
        of the Phase 6 review fix is that MED writes never go through
        approval blind.
        """
        if action == "write_file":
            path = args.get("path")
            new_content = args.get("content")
            if not isinstance(path, str) or new_content is None:
                return None
            return summarize_write(
                path=path,
                new_content=new_content,
                old_content=current_content,
            )

        if action == "payload_badusb_create":
            # Synthesise the target path the tool will compute.
            name = args.get("name")
            script_text = args.get("script_text")
            if not isinstance(name, str) or not isinstance(script_text, str):
                return None
            fname = name if name.endswith(".txt") else f"{name}.txt"
            path = f"/ext/badusb/{fname}"
            return summarize_write(
                path=path,
                new_content=script_text,
                old_content=current_content,
            )

        if action == "payload_subghz_retune":
            source_path = args.get("source_path")
            dest_name = args.get("dest_name")
            if not isinstance(source_path, str) or not isinstance(dest_name, str):
                return None
            dest_fname = dest_name if dest_name.endswith(".sub") else f"{dest_name}.sub"
            dest_path = f"/ext/subghz/{dest_fname}"
            # The retune preview — if the hooks layer assembled one and
            # stuck it in `_preview_content`, use that. Otherwise fall
            # back to a metadata-only description ("new file, freq
            # X→Y"). Both produce a non-None DiffSummary so the reviewer
            # invariant ("MED writes never blind") holds.
            preview = args.get("_preview_content")
            if preview is not None:
                return summarize_write(
                    path=dest_path,
                    new_content=preview,
                    old_content=current_content,
                )
            freq = args.get("frequency_hz")
            preset = args.get("preset")
            descr_parts: list[str] = []
            if freq is not None:
                descr_parts.append(f"Frequency -> {freq}")
            if preset is not None:
                descr_parts.append(f"Preset -> {preset}")
            descr = "; ".join(descr_parts) or "no header changes"
            placeholder = (
                f"(subghz retune of {source_path} -> {dest_path})\n"
                f"{descr}\n"
            )
            return summarize_write(
                path=dest_path,
                new_content=placeholder,
                old_content=current_content,
            )

        if action in ("payload_subghz_import_capture", "payload_ir_import_capture"):
            source_path = args.get("source_path")
            dest_name = args.get("dest_name")
            if not isinstance(source_path, str) or not isinstance(dest_name, str):
                return None
            ext = ".sub" if action == "payload_subghz_import_capture" else ".ir"
            root = (
                "/ext/subghz" if action == "payload_subghz_import_capture"
                else "/ext/infrared"
            )
            dest_fname = dest_name if dest_name.endswith(ext) else f"{dest_name}{ext}"
            dest_path = f"{root}/{dest_fname}"
            # Import-capture doesn't rewrite file contents — only
            # renames + writes a sidecar. Show a rename-intent diff plus
            # the sidecar metadata so the operator sees what's being
            # committed to disk.
            description = args.get("description") or ""
            tags = args.get("tags") or []
            author = args.get("author") or ""
            pseudo = (
                f"(rename {source_path} -> {dest_path})\n"
                f"(sidecar will be written at {dest_path[:-len(ext)]}.echoforge.json)\n"
                f"  description: {description}\n"
                f"  author: {author}\n"
                f"  tags: {', '.join(tags) if tags else '(none)'}\n"
            )
            return summarize_write(
                path=dest_path,
                new_content=pseudo,
                old_content=current_content,
            )

        return None
