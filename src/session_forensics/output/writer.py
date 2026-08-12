"""Atomic digest write: a unique temp file in the same directory, then
`os.replace`.

Same-volume rename is atomic on Windows, and `os.replace` overwrites where
`os.rename` does not -- the latter raises `FileExistsError` on Windows when the
destination already exists, which every update after the first would hit.
Interrupting between the write and the rename leaves the previous digest intact
and at most a stray temp file, never a half-written digest at the real path.

The temp filename is unique per call (`tempfile.mkstemp`, not a fixed `<name>.tmp`)
so that even if two writes for the same session somehow overlap -- the lock file
(T4.4) is meant to prevent this, but spec.md requires the write itself to stay
safe regardless -- they write to independent files and the last `os.replace`
simply wins cleanly, with no interleaved corruption possible.

Measured directly (concurrent-writer test during T4.2): `os.replace` onto a
destination another thread is *also* replacing at that exact instant can raise
a transient `PermissionError` (WinError 5) on Windows, even though the
underlying rename is atomic and the file itself is never left corrupted. A
short bounded retry absorbs this rather than surfacing a spurious failure for
what resolves in milliseconds.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

__all__ = ["write_atomic"]

_REPLACE_RETRIES = 5
_REPLACE_RETRY_DELAY_SECONDS = 0.05


def write_atomic(path: str | Path, content: str) -> None:
    """Write `content` to `path` atomically. UTF-8 and `\\n` line endings pinned
    explicitly, not left to the platform default -- Windows text mode would
    otherwise translate `\\n` to `\\r\\n`, which would break render.py's
    byte-identical-output guarantee.
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def _replace_with_retry(src: str, dst: Path) -> None:
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_SECONDS)
