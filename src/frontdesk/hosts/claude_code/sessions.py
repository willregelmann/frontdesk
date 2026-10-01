"""Which Claude Code session a process belongs to.

Claude Code tells hooks the session id but not the MCP servers it spawns. Both are descendants of
the same Claude Code process, so a hook records the id against each of its ancestors, and the server
looks up its own ancestors nearest first: the first one they share is that Claude Code process.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional


def _parent(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return int(fh.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        try:
            out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip() or 0)
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0


def _started(pid: int) -> str:
    """Something that differs between two processes that were given the same pid at different times."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return ""


def ancestors(pid: Optional[int] = None) -> list[int]:
    chain, pid = [], _parent(pid or os.getpid())
    while pid > 1 and pid not in chain:
        chain.append(pid)
        pid = _parent(pid)
    return chain


def _dir(home: Path) -> Path:
    return Path(home) / "claude-sessions"


def record(home: Path, session_id: str) -> None:
    directory = _dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    for pid in ancestors():
        (directory / str(pid)).write_text(json.dumps({"session": session_id, "started": _started(pid)}))


def current(home: Path) -> Optional[str]:
    directory = _dir(home)
    for pid in ancestors():
        try:
            entry = json.loads((directory / str(pid)).read_text())
        except (OSError, ValueError):
            continue
        if entry.get("started") == _started(pid):
            return entry.get("session")
    return None
