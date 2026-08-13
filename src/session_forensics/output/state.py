"""Per-session state sidecar: `.decisions/.state/<session-id>.json`.

The single source of truth the digest is rebuilt from on every update -- not
the rendered markdown, which is a derived view and is never read back
(plan.md's state sidecar section: "nothing here is human-facing -- the
markdown is"). A corrupt or missing sidecar is treated as "no checkpoint": the
session reprocesses from the start rather than raising, since losing this file
must cost re-processing, never break the tool.

Extends plan.md's originally-listed field set (checkpoint_event,
checkpoint_line, entry_ids, calls, tokens_in, tokens_out, last_success_utc,
last_error, provider, tool_version) with the rest of `Digest`'s state -- see
plan.md § Data Model. `existing_titles` for the prompt (T3.4) and the
render-time running totals (tools, files touched, timestamps, T3.6) both need
somewhere to persist between updates, and re-deriving them by parsing the
tool's own rendered markdown back is exactly the anti-pattern the design
avoids elsewhere. `entry_ids` specifically is dropped as a separate field:
it is fully redundant with `entries[].id` and storing both would just be two
copies that could disagree.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from ..digest.model import Digest, Entry
from .writer import write_atomic

__all__ = ["SessionState", "save", "load"]


@dataclass
class SessionState:
    digest: Digest
    checkpoint_event: int = 0
    checkpoint_line: int = 0
    tool_version: str = __version__


def save(state: SessionState, path: str | Path) -> None:
    """Write the sidecar atomically. Creates `.state/` if needed -- the same
    write-gate spirit as output/locate.py, minimal here since `.decisions/`
    itself (and its `.gitignore`) is already guaranteed to exist by the time
    any state is saved.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _to_dict(state)
    write_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def load(path: str | Path) -> SessionState | None:
    """`None` on anything short of a fully valid sidecar -- missing, unreadable,
    malformed JSON, or a shape this module doesn't recognise. Callers treat
    `None` as "no checkpoint, reprocess from the start," never as an error to
    raise -- a lost or damaged sidecar must cost re-processing, not availability.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return _from_dict(payload)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _to_dict(state: SessionState) -> dict:
    d = state.digest
    return {
        "session_id": d.session_id,
        "checkpoint_event": state.checkpoint_event,
        "checkpoint_line": state.checkpoint_line,
        "tool_version": state.tool_version,
        "entries": [
            {
                "id": e.id, "section": e.section, "text": e.text, "why": e.why,
                "turns": list(e.turns) if e.turns else None, "added_at": e.added_at,
            }
            for e in d.entries
        ],
        "calls": d.calls,
        "tokens_in": d.tokens_in,
        "tokens_out": d.tokens_out,
        "model": d.model,
        "provider": d.provider,
        "turns_covered": d.turns_covered,
        "turns_pending": d.turns_pending,
        "last_success": d.last_success,
        "last_error": d.last_error,
        "cap_reached": d.cap_reached,
        "optout": d.optout,
        "no_key": d.no_key,
        "unparseable_lines": d.unparseable_lines,
        "dropped_tokens": d.dropped_tokens,
        "dropped_entries": d.dropped_entries,
        "tools": dict(d.tools),
        "files_touched_in_cwd": sorted(d.files_touched_in_cwd),
        "files_touched_outside_cwd": sorted(d.files_touched_outside_cwd),
        "session_started": d.session_started,
        "session_ended": d.session_ended,
        "branch": d.branch,
        "compaction_count": d.compaction_count,
        "ai_title": d.ai_title,
        "custom_title": d.custom_title,
    }


def _from_dict(payload: dict) -> SessionState:
    entries = [
        Entry(
            id=e["id"], section=e["section"], text=e["text"], why=e.get("why"),
            turns=tuple(e["turns"]) if e.get("turns") else None, added_at=e["added_at"],
        )
        for e in payload["entries"]
    ]
    digest = Digest(
        session_id=payload["session_id"],
        entries=entries,
        calls=payload.get("calls", 0),
        tokens_in=payload.get("tokens_in", 0),
        tokens_out=payload.get("tokens_out", 0),
        model=payload.get("model"),
        provider=payload.get("provider"),
        turns_covered=payload.get("turns_covered", 0),
        turns_pending=payload.get("turns_pending", 0),
        last_success=payload.get("last_success"),
        last_error=payload.get("last_error"),
        cap_reached=payload.get("cap_reached", False),
        optout=payload.get("optout", False),
        no_key=payload.get("no_key", False),
        unparseable_lines=payload.get("unparseable_lines", 0),
        dropped_tokens=payload.get("dropped_tokens", 0),
        dropped_entries=payload.get("dropped_entries", 0),
        tools=Counter(payload.get("tools") or {}),
        files_touched_in_cwd=set(payload.get("files_touched_in_cwd") or []),
        files_touched_outside_cwd=set(payload.get("files_touched_outside_cwd") or []),
        session_started=payload.get("session_started"),
        session_ended=payload.get("session_ended"),
        branch=payload.get("branch"),
        compaction_count=payload.get("compaction_count", 0),
        ai_title=payload.get("ai_title"),
        custom_title=payload.get("custom_title"),
    )
    return SessionState(
        digest=digest,
        checkpoint_event=payload.get("checkpoint_event", 0),
        checkpoint_line=payload.get("checkpoint_line", 0),
        tool_version=payload.get("tool_version", "unknown"),
    )
