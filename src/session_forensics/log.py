"""Size-capped diagnostic logger.

Destination is supplied by the caller -- this module knows nothing about
`.decisions/` or session ids, only how to append a capped, UTF-8 line to a file.
Every hook and worker failure must be diagnosable without ever writing to stdout
or stderr from a hook context (spec.md: diagnostics go to a log file inside the
ignored output directory, never to stdout/stderr). `hookrunner.py` deliberately
does not import this module -- see plan.md's import allowlist for it -- so a
below-threshold hook exit is silent by design; the worker is where diagnostics
start.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

from . import config

__all__ = ["log", "debug", "info", "warning", "error"]

#: Once the file exceeds this many bytes, it is truncated to its tail before the
#: new line is appended, rather than growing without bound across a project's
#: lifetime.
MAX_BYTES = 1_000_000
_KEEP_BYTES = MAX_BYTES // 2

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


def log(path: str | Path, level: str, message: str, *, session_id: str | None = None) -> None:
    """Append one line to `path`. Never raises.

    A logging failure -- disk full, directory gone, permission denied -- must
    never become the reason the caller itself fails; every entry point that calls
    this is already inside its own top-level failure handling.
    """
    try:
        _log(Path(path), level.upper(), message, session_id)
    except Exception:
        pass


def debug(path: str | Path, message: str, **kw) -> None:
    log(path, "DEBUG", message, **kw)


def info(path: str | Path, message: str, **kw) -> None:
    log(path, "INFO", message, **kw)


def warning(path: str | Path, message: str, **kw) -> None:
    log(path, "WARNING", message, **kw)


def error(path: str | Path, message: str, **kw) -> None:
    log(path, "ERROR", message, **kw)


def _log(path: Path, level: str, message: str, session_id: str | None) -> None:
    threshold = _LEVELS.get(config.log_level(), 20)
    if _LEVELS.get(level, 20) < threshold:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tag = f" [{session_id}]" if session_id else ""
    line = f"{stamp} {level}{tag} {message}\n"
    with open(path, "a", encoding="utf-8", newline="") as handle:
        handle.write(line)


def _rotate_if_needed(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= MAX_BYTES:
        return
    with open(path, "rb") as handle:
        handle.seek(-_KEEP_BYTES, os.SEEK_END)
        tail = handle.read()
    newline = tail.find(b"\n")  # drop a possibly-truncated first line
    if newline != -1:
        tail = tail[newline + 1:]
    with open(path, "wb") as handle:
        handle.write(tail)
