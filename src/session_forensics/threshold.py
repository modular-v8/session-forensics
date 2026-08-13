"""Cheap trigger gating for hookrunner.py: should this Stop fire spawn a worker?

hookrunner.py cannot open the transcript (spec.md: it must return control in
under a second, on a path the user is waiting on after every turn) and cannot
import `output/` (plan.md's import allowlist keeps its dependency graph
minimal). This module is the resolution: it tracks its own tiny, separate
counter file -- `.decisions/.state/<session-id>.trigger.json` -- using only
`os.stat()` on the transcript (size, never its content) and a fire-count that
approximates "turns since checkpoint" from something cheaper and arguably more
accurate than parsing the transcript: `Stop` fires once per assistant turn
(plan.md § Architecture), so counting firings *is* counting turns.

This file is deliberately separate from output/state.py's sidecar and from
worker.py's checkpoint entirely. It is a best-effort optimisation, not a
correctness mechanism: if it is ever wrong -- stale, missing, corrupted, or a
worker crashes right after this module decided to trigger -- the worst case is
one redundant spawn, immediately absorbed by the lock file (T4.4), or one
delayed update, caught by the next trigger. worker.py's own checkpoint
(output/state.py) is the only thing that determines what has actually been
processed; nothing here is allowed to affect correctness, only frequency.

Consequence of never creating `.decisions/` itself (only output/locate.py's
write-gated path may do that -- creating it here, unprotected, could leave an
untracked file in a fresh repo): until the first worker run succeeds and
creates `.decisions/.state/`, this always reports "trigger". That is bounded
and safe (see above), not a bug.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import config
from .repo import repo_root

__all__ = ["should_trigger", "mark_retry_pending", "clear_retry_pending"]


def should_trigger(*, session_id: str, transcript_path: str, cwd: str) -> bool:
    """True if enough has changed since the last trigger to be worth spawning
    a worker. Always best-effort: any failure reading, parsing or writing the
    trigger file is treated as "yes, trigger" and otherwise swallowed --
    hookrunner has nowhere safe to report a problem, and erring toward
    triggering is the safe direction (a redundant spawn costs little; a
    silently-skipped one costs a stale digest).

    Also triggers unconditionally, regardless of turn/char count, whenever a
    retryable provider failure is outstanding (`mark_retry_pending`, below) --
    spec.md's "SHALL retry on the next trigger" means the very next `Stop`,
    not the next one that also happens to cross the normal threshold. Found
    directly: a real retryable failure resets nothing about the turn/char
    counters below (they are a *frequency* heuristic, tracking fires since the
    last trigger, not the last *successful* one), so without this a failure
    landing right after a fresh reset could sit unretried for up to another
    full `SF_TURN_THRESHOLD` turns even though the underlying rate-limit
    window that caused it is typically sub-minute (tasks.md T4.10).
    """
    try:
        current_size = os.stat(transcript_path).st_size
    except OSError:
        return True  # can't even stat it; let the worker sort that out and log properly

    trigger_path = _trigger_path(session_id, cwd)
    state = _read(trigger_path)
    bytes_at_checkpoint = state.get("bytes_at_checkpoint", 0)
    fires_since_checkpoint = state.get("fires_since_checkpoint", 0) + 1
    pending_failure = bool(state.get("pending_failure", False))

    new_bytes = max(0, current_size - bytes_at_checkpoint)
    trigger = (
        state == {}  # no prior baseline at all -- see module docstring
        or fires_since_checkpoint >= config.turn_threshold()
        or new_bytes >= config.char_threshold()
        or pending_failure
    )

    # `pending_failure` is carried forward either way -- only worker.py, which
    # actually knows the outcome, clears it (`clear_retry_pending`). Triggering
    # because of it does not itself mean the resulting worker run will succeed.
    if trigger:
        _write(trigger_path, {"bytes_at_checkpoint": current_size, "fires_since_checkpoint": 0, "pending_failure": pending_failure})
    else:
        _write(trigger_path, {"bytes_at_checkpoint": bytes_at_checkpoint, "fires_since_checkpoint": fires_since_checkpoint, "pending_failure": pending_failure})

    return trigger


def mark_retry_pending(session_id: str, cwd: str) -> None:
    """Called by worker.py right after a retryable provider failure. Makes the
    *next* `should_trigger()` call for this session return `True`
    unconditionally, so recovery from a short-lived rate-limit window (T4.10:
    observed sub-minute) happens on the next real `Stop`, typically the user's
    very next turn -- not gated behind another full threshold's worth of
    turns/characters. Best-effort, matching this module's existing file I/O:
    a failure to write here costs one missed fast-retry opportunity, never
    correctness (worker.py's own checkpoint is unaffected either way).
    """
    path = _trigger_path(session_id, cwd)
    state = _read(path)
    state["pending_failure"] = True
    _write(path, state)


def clear_retry_pending(session_id: str, cwd: str) -> None:
    """Called by worker.py after every update that succeeds -- clearing an
    already-clear flag is a harmless no-op, so callers never need to know
    whether a failure was actually pending first.
    """
    path = _trigger_path(session_id, cwd)
    state = _read(path)
    if state.get("pending_failure"):
        state["pending_failure"] = False
        _write(path, state)


def _trigger_path(session_id: str, cwd: str) -> Path:
    return repo_root(cwd) / config.out_dir() / ".state" / f"{session_id}.trigger.json"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    """Best-effort: if `.decisions/.state/` does not exist yet, this silently
    does nothing rather than creating it -- see module docstring. Not atomic
    (no writer.py import allowed here either): this file is a cheap heuristic,
    never read by anything that requires correctness, so a torn write in the
    rare crash-mid-write case only costs one extra trigger next time.
    """
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except OSError:
        pass
