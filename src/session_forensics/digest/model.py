"""`Entry` and `Digest` -- the persisted shape a rendered digest describes.

`Entry.id` is a SHA-1 of normalised text (lower-cased, punctuation-stripped) so
deduplication survives re-summarisation of overlapping material: two calls that
both notice the same decision, worded identically after normalisation, collapse
to one entry instead of two. Cheap, deterministic, no model involved (plan.md §
Tech Stack).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field

__all__ = ["Entry", "Digest", "entry_id", "SECTIONS"]

SECTIONS = ("decided", "rejected", "open")

_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def entry_id(text: str) -> str:
    """SHA-1 of `text`, lower-cased and punctuation-stripped. The dedup key."""
    normalised = _SPACE.sub(" ", _PUNCT.sub("", text.lower())).strip()
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Entry:
    id: str
    section: str  # one of SECTIONS -- anything else from the model was already dropped
    text: str  # truncated to the configured word cap
    why: str | None
    turns: tuple[int, int] | None  # transcript event range this entry was drawn from
    added_at: str  # ISO timestamp of the update that produced it


@dataclass
class Digest:
    session_id: str
    entries: list[Entry] = field(default_factory=list)

    # Footer counters -- plan.md § Data Model.
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None
    provider: str | None = None
    turns_covered: int = 0
    turns_pending: int = 0
    last_success: str | None = None
    last_error: str | None = None
    cap_reached: bool = False
    optout: bool = False
    #: No GEMINI_API_KEY or OPENROUTER_API_KEY in the environment. A distinct
    #: state from cap_reached/optout because spec.md requires each to state its
    #: own reason -- added at T3.8, not in the original footer field list.
    no_key: bool = False
    unparseable_lines: int = 0
    dropped_tokens: int = 0
    #: Entries the model returned but a section was already at its cap.
    #: Not in plan.md's original footer field list -- added here because the
    #: "oldest entries win" cap-overflow decision requires a count in the
    #: footer, and there was nowhere to put it. See plan.md § Data Model.
    dropped_entries: int = 0

    # Whole-session running totals for the render-time strapline (T3.6).
    # Accumulated incrementally by digest/merge.py::accumulate_session_stats
    # from each delta's Facts -- never a full transcript re-parse. Not in
    # plan.md's original Digest field list; see plan.md § Data Model.
    tools: Counter = field(default_factory=Counter)
    files_touched_in_cwd: set[str] = field(default_factory=set)
    files_touched_outside_cwd: set[str] = field(default_factory=set)
    session_started: str | None = None
    session_ended: str | None = None
    branch: str | None = None
    compaction_count: int = 0
    #: Claude Code's own session title (T4.14). See `title` below for the
    #: effective value -- `custom_title` (a title the user set themselves)
    #: always wins over `ai_title` (auto-generated) when both are present.
    ai_title: str | None = None
    custom_title: str | None = None

    def by_section(self, section: str) -> list[Entry]:
        return [e for e in self.entries if e.section == section]

    @property
    def title(self) -> str | None:
        """The human-readable name to show for this session, if any is known
        yet -- `None` for a session too new to have one (falls back to the
        session id wherever this is displayed).
        """
        return self.custom_title or self.ai_title
