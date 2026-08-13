"""Append-only merge: new entries in, caps and dedup enforced in code.

Existing entries are never modified -- only appended to. Caps are enforced here
regardless of what the model was asked for or how well it complied (spec.md:
"enforced... by truncation in code, independently of the model's output").
Two different failure shapes, two different responses: a *word-count* overflow
is truncated (the entry survives, shortened); a *section-count* overflow is
dropped entirely once that section is already at its cap, oldest entries
winning (plan.md § Tech Stack: "Cap overflow").
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable, Protocol

from .. import config
from ..extract.delta import Delta
from .model import SECTIONS, Digest, Entry, entry_id

__all__ = ["merge_entries", "accumulate_session_stats"]


class _RawEntry(Protocol):
    """What `digest/prompt.py`'s `ParsedEntry` looks like -- structural, not a
    hard dependency, so a fake entry in a test needs no import from prompt.py.
    """

    section: str
    text: str
    why: str | None
    turns: tuple[int, int] | None


def merge_entries(digest: Digest, parsed: Iterable[_RawEntry], *, timestamp: str) -> int:
    """Append entries from `parsed` that are new, truncated to the word cap,
    dropping any whose section is already at its cap. Returns the count
    actually added. Feeding the same entries again adds nothing: identity is
    computed from the same normalised text every time.
    """
    caps = config.section_caps()
    cap_words = config.word_cap()
    existing_ids = {e.id for e in digest.entries}
    counts = Counter(e.section for e in digest.entries)
    added = 0
    dropped_for_cap = 0

    for item in parsed:
        if item.section not in SECTIONS:
            continue  # digest/prompt.py already filters this; defence in depth
        if counts[item.section] >= caps.get(item.section, 0):
            dropped_for_cap += 1
            continue

        text = _truncate_words(item.text, cap_words)
        if not text:
            continue
        why = _truncate_words(item.why, cap_words) if item.why else None
        eid = entry_id(text)
        if eid in existing_ids:
            continue

        digest.entries.append(Entry(
            id=eid, section=item.section, text=text, why=why,
            turns=item.turns, added_at=timestamp,
        ))
        existing_ids.add(eid)
        counts[item.section] += 1
        added += 1

    digest.dropped_entries += dropped_for_cap
    return added


def _truncate_words(text: str, cap: int) -> str:
    words = text.split()
    if len(words) <= cap:
        return text
    return " ".join(words[:cap]) + "…"


def accumulate_session_stats(digest: Digest, delta: Delta, *, cwd: str | None = None) -> None:
    """Fold one delta's mechanical facts into the digest's whole-session running
    totals -- tool composition, files touched, compaction loss, timestamps,
    branch. Incremental by design, same as `merge_entries`: this never re-parses
    the transcript, only the new delta already streamed from the checkpoint.

    File paths are kept only to be counted (`len(...)`), never individually
    rendered -- digest/render.py's strapline shows "N files touched", not a
    list. Splitting in-cwd from outside-cwd exists so scratch/temp files never
    inflate that count the way they did in the deleted pre-pivot renderer.
    """
    facts = delta.facts
    digest.tools.update(facts.tools)

    for path in set(facts.files_written) | set(facts.files_edited):
        if cwd and not _is_under(path, cwd):
            digest.files_touched_outside_cwd.add(path)
        else:
            digest.files_touched_in_cwd.add(path)

    digest.unparseable_lines += delta.unparseable
    digest.compaction_count += len(delta.compactions)
    if delta.compactions:
        digest.dropped_tokens = max([digest.dropped_tokens] + [c[1] for c in delta.compactions])

    if digest.session_started is None and delta.session_started:
        digest.session_started = delta.session_started
    if delta.session_ended:
        digest.session_ended = delta.session_ended
    if digest.branch is None and delta.branch:
        digest.branch = delta.branch

    # Unlike branch/session_started (set once, sticky), a title can
    # legitimately be renamed mid-session -- the latest value this delta
    # happens to carry replaces whatever was recorded before, so a rename
    # picked up by a later update is reflected, not stuck on the first title
    # ever seen.
    if delta.ai_title:
        digest.ai_title = delta.ai_title
    if delta.custom_title:
        digest.custom_title = delta.custom_title


def _is_under(path: str, cwd: str) -> bool:
    """True if `path` resolves to somewhere inside `cwd`.

    A relative `path` is joined onto `cwd` explicitly rather than left to
    `Path.resolve()`'s implicit use of the current process's directory --
    worker.py's process is never the session's own working directory, so that
    default would silently misclassify every relative path.
    """
    try:
        base = Path(cwd).resolve()
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = base / candidate
        return candidate.resolve().is_relative_to(base)
    except (OSError, ValueError):
        return False
