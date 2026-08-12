"""Repository root resolution -- the one piece of path logic shared between
`output/locate.py` (the full write gate) and `threshold.py` (hookrunner's cheap
trigger check, which cannot import `output/`). Deliberately dependency-free
beyond `pathlib` so both sides of that boundary can use it.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["repo_root"]


def repo_root(cwd: str | Path) -> Path:
    """Walk up from `cwd` for a `.git` entry; fall back to `cwd` when none is
    found. `.git` may be a directory (a normal clone) or a file (a worktree or
    submodule points elsewhere) -- either is a valid anchor here, since only
    its *presence* matters, not its contents.
    """
    current = Path(cwd).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current
