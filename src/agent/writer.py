"""
writer.py — ADR file I/O for the ADR Agent.

Handles atomic writes, file-locked sequence allocation, and revision appending.
"""

from __future__ import annotations

import datetime
import sys
import threading
from pathlib import Path

_SEQUENCE_LOCK = threading.Lock()


def next_sequence(decisions_dir: Path) -> int:
    """Return the next ADR sequence number. Thread-safe: process lock + optional flock."""
    decisions_dir.mkdir(parents=True, exist_ok=True)

    with _SEQUENCE_LOCK:
        if sys.platform != "win32":
            import fcntl
            lock_path = decisions_dir / ".adr-sequence.lock"
            with open(lock_path, "w") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                seq = _compute_next(decisions_dir)
        else:
            seq = _compute_next(decisions_dir)

    return seq


def _compute_next(decisions_dir: Path) -> int:
    numbers = []
    for f in decisions_dir.glob("ADR-*.md"):
        parts = f.name.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            numbers.append(int(parts[1]))
    return max(numbers) + 1 if numbers else 1


def write_adr(content: str, adr_path: Path) -> Path:
    """Atomically write content to adr_path via a .tmp intermediate then rename."""
    adr_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = adr_path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.rename(adr_path)
    return adr_path


def append_revision(adr_path: Path, reason: str) -> None:
    """Append a dated revision entry to an existing ADR. Never truncates existing content."""
    today = datetime.date.today().isoformat()
    current = adr_path.read_text(encoding="utf-8")

    if "## Revision history" in current:
        updated = current.rstrip() + f"\n- {today}: {reason}\n"
    else:
        updated = current.rstrip() + f"\n\n---\n\n## Revision history\n\n- {today}: {reason}\n"

    write_adr(updated, adr_path)
