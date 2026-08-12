"""Per-project opt-out marker.

`.decisions-optout` at the repository root switches a project to
deterministic-only output with nothing transmitted -- spec.md's answer to a
corpus that, in practice, contains job applications and financial records.
Requiring the user to remember which directories are sensitive is a control
that fails quietly; a visible file in a directory listing does not.

This module only detects the marker. Where "repository root" comes from is
output/locate.py's job (T4.1); worker.py (T4.5) is what actually short-circuits
before extract/delta.py runs -- checked there, not here, since the marker alone
proves nothing about which code path reads it.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["MARKER_NAME", "is_opted_out"]

MARKER_NAME = ".decisions-optout"


def is_opted_out(root: str | Path) -> bool:
    """True if `root` -- a repository root, not necessarily `cwd` -- carries the marker."""
    return (Path(root) / MARKER_NAME).is_file()
