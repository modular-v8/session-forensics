"""Streaming JSONL reader. One line at a time, tolerant of damage."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

__all__ = ["read_records"]


def read_records(path: str | Path, *, after_line: int = 0) -> Iterator[tuple[int, dict | None]]:
    """Yield ``(line_number, record)`` for every line, ``None`` where parsing failed.

    Never loads the file whole: a 7 MB transcript costs the same memory as a 90 KB
    one. Yielding ``None`` rather than skipping lets the caller count damage and
    report it, which the summary is required to do.

    ``after_line`` skips straight past every line up to and including it, with no
    ``json.loads`` call on any of them -- not just cheaper processing, no
    processing. Default ``0`` reads every line, exactly as before this parameter
    existed; extract/delta.py is the only caller that passes a nonzero value, to
    stream a delta from a checkpoint rather than re-parsing a transcript from the
    start.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        if after_line > 0:
            for _ in range(after_line):
                if handle.readline() == "":
                    return  # file is shorter than the checkpoint; nothing new
        for number, line in enumerate(handle, start=after_line + 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                yield number, None
                continue
            yield number, record if isinstance(record, dict) else None
