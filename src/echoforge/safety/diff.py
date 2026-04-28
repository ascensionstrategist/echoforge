"""
Diff rendering for file-write approval prompts.

For text files: unified diff with configurable context lines.
For binary files: hex summary (first/last bytes + size delta + md5).

The output is a single string suitable for display in a terminal, TUI
pane, or dialog. Diff generation is stateless — no service object to
spin up; everything is free functions.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from typing import Optional, Union


# Heuristic: byte arrays containing NUL are treated as binary.
# Otherwise we try UTF-8 decoding; if that fails, treat as binary.
def is_binary(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _decode_text(data: Union[bytes, str]) -> str:
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class DiffSummary:
    """Lightweight summary of a proposed write."""
    path: str
    is_new: bool
    is_binary: bool
    old_size: int
    new_size: int
    diff_text: str        # ready-to-display unified diff or hex summary
    lines_added: int = 0
    lines_removed: int = 0

    @property
    def size_delta(self) -> int:
        return self.new_size - self.old_size


def unified_text_diff(
    old: str,
    new: str,
    *,
    path: str = "",
    context: int = 3,
) -> tuple[str, int, int]:
    """Return (diff_text, lines_added, lines_removed) for two text blobs.

    Empty diff_text means the content is identical.
    """
    if old == new:
        return ("", 0, 0)

    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    # Ensure a trailing newline so difflib doesn't emit "\ No newline at
    # end of file" noise on the last chunk.
    if old_lines and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    label = path or "file"
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{label}",
        tofile=f"b/{label}",
        n=context,
        lineterm="\n",
    )

    lines_added = 0
    lines_removed = 0
    diff_chunks: list[str] = []
    for line in diff:
        diff_chunks.append(line)
        if line.startswith("+") and not line.startswith("+++"):
            lines_added += 1
        elif line.startswith("-") and not line.startswith("---"):
            lines_removed += 1

    return ("".join(diff_chunks), lines_added, lines_removed)


def binary_diff_summary(
    old: bytes,
    new: bytes,
    *,
    path: str = "",
    preview_bytes: int = 32,
) -> str:
    """Human-readable summary of a binary file change."""
    old_md5 = hashlib.md5(old).hexdigest() if old else "-"
    new_md5 = hashlib.md5(new).hexdigest() if new else "-"
    delta = len(new) - len(old)
    arrow = "→"
    sign = "+" if delta > 0 else ""

    def _preview(data: bytes) -> str:
        if not data:
            return "(empty)"
        head = data[:preview_bytes].hex(" ")
        if len(data) <= preview_bytes * 2:
            return head
        tail = data[-preview_bytes:].hex(" ")
        return f"{head}  ...  {tail}"

    return (
        f"(binary) {path}\n"
        f"  size:  {len(old):,} B {arrow} {len(new):,} B  ({sign}{delta:,})\n"
        f"  md5:   {old_md5}  {arrow}  {new_md5}\n"
        f"  old:   {_preview(old)}\n"
        f"  new:   {_preview(new)}\n"
    )


def summarize_write(
    path: str,
    new_content: Union[bytes, str],
    *,
    old_content: Optional[Union[bytes, str]] = None,
    context: int = 3,
) -> DiffSummary:
    """
    Produce a `DiffSummary` suitable for displaying in an approval prompt.

    `old_content=None` signals a brand-new file (caller's storage layer
    reported "not exist"). For updates, pass the current file contents.
    """
    is_new = old_content is None

    # Normalize for binary detection
    new_bytes = new_content.encode("utf-8") if isinstance(new_content, str) else new_content
    old_bytes = b"" if old_content is None else (
        old_content.encode("utf-8") if isinstance(old_content, str) else old_content
    )

    binary = is_binary(new_bytes) or (not is_new and is_binary(old_bytes))

    if binary:
        return DiffSummary(
            path=path,
            is_new=is_new,
            is_binary=True,
            old_size=len(old_bytes),
            new_size=len(new_bytes),
            diff_text=binary_diff_summary(old_bytes, new_bytes, path=path),
        )

    old_text = "" if is_new else _decode_text(old_bytes)
    new_text = _decode_text(new_bytes)
    diff_text, added, removed = unified_text_diff(old_text, new_text, path=path, context=context)

    if is_new:
        # For brand-new files, show first N lines as preview rather than diff.
        preview_lines = new_text.splitlines()
        preview = "\n".join(preview_lines[:20])
        if len(preview_lines) > 20:
            preview += f"\n... (+{len(preview_lines) - 20} more lines)"
        diff_text = f"(new file) {path}\n{preview}\n"
        added = len(preview_lines)

    return DiffSummary(
        path=path,
        is_new=is_new,
        is_binary=False,
        old_size=len(old_bytes),
        new_size=len(new_bytes),
        diff_text=diff_text,
        lines_added=added,
        lines_removed=removed,
    )
