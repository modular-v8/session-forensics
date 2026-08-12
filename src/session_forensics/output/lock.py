"""Worker lock: `.decisions/.state/<session-id>.lock`.

A second worker for the same session exits immediately rather than racing the
first -- `Stop` can fire again while a worker spawned on a previous turn is
still running (plan.md § Tech Stack: concurrency). A lock older than
`config.LOCK_STALE_SECONDS` is treated as stale and taken over: a crashed
worker leaving a lock behind must not disable summarising for that session
permanently.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from .. import config

__all__ = ["Lock", "acquire"]


class Lock:
    """A held lock. Use as a context manager, or call `release()` directly."""

    def __init__(self, path: Path):
        self._path = path
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            self._path.unlink()
        except OSError:
            pass  # already gone -- another process cleaning up is not our problem

    def __enter__(self) -> Lock:
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


def acquire(path: str | Path) -> Lock | None:
    """Attempt to acquire the lock at `path`.

    Returns `None` if another worker already holds it and it is not stale --
    the caller's job is to exit immediately in that case, not to wait or retry
    (this is a Stop-hook-triggered worker, not a queue).

    Creation is atomic (`O_CREAT | O_EXCL`, no separate check-then-create
    window), so even two processes racing to take over the same stale lock at
    the same instant leave exactly one of them holding it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if _try_create(path):
        return Lock(path)

    if _is_stale(path):
        try:
            path.unlink()
        except OSError:
            pass  # someone else already cleaned it up or took it over first
        if _try_create(path):
            return Lock(path)

    return None


def _try_create(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
    finally:
        os.close(fd)
    return True


def _is_stale(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False  # vanished between the failed create and this check -- not ours to judge
    return age > config.LOCK_STALE_SECONDS
