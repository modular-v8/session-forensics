"""Merge every digest in a project into one chronologically ordered document.

The stated deliverable (spec.md § outcome): writing a report about an
application built across dozens of sessions, where the reasoning behind each
choice currently lives only inside transcripts nobody reopens.

Reads the state sidecars under `.decisions/.state/` -- the source of truth --
never the rendered markdown digests, consistent with the rest of this design
(the markdown is a derived view, never parsed back; see output/state.py).
Ordering is by each *entry's* own `added_at` timestamp, not a session's start
time or its filename: this is finer-grained than sorting session-by-session
and correctly interleaves entries added at different points within sessions
that overlapped in time. Deduplication reuses `Entry.id` -- the same
normalised-text SHA-1 `digest/merge.py` computes -- so a decision recorded
independently in two sessions collapses to one, attributed to whichever
recorded it first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .digest.model import Entry, SECTIONS
from .output import locate
from .output import state as state_mod

__all__ = ["AggregatedEntry", "aggregate", "render_aggregate"]


@dataclass(frozen=True)
class AggregatedEntry:
    entry: Entry
    session_id: str
    #: Best available date for the *session* (its recorded start, falling
    #: back to its last successful update) -- distinct from `entry.added_at`,
    #: which is when this specific entry was added within that session.
    session_date: str | None
    #: Claude Code's own session title (T4.14), when the session has one --
    #: `None` for a session too new to have been assigned one. This is what
    #: makes the merged report navigable by name rather than by session id.
    session_title: str | None = None


def aggregate(decisions_dir: str | Path) -> list[AggregatedEntry]:
    """Read every session sidecar under `decisions_dir`, deduplicate across
    all of them, and return the survivors ordered by each entry's own
    `added_at` timestamp. Empty (not an error) if `decisions_dir` has no
    sessions yet.
    """
    candidates = [
        AggregatedEntry(
            entry=entry,
            session_id=session_id,
            session_date=session_state.digest.session_started or session_state.digest.last_success,
            session_title=session_state.digest.title,
        )
        for session_id, session_state in _load_sessions(decisions_dir)
        for entry in session_state.digest.entries
    ]
    candidates.sort(key=lambda a: a.entry.added_at or "")

    seen: set[str] = set()
    out: list[AggregatedEntry] = []
    for candidate in candidates:
        if candidate.entry.id in seen:
            continue
        seen.add(candidate.entry.id)
        out.append(candidate)
    return out


def _load_sessions(decisions_dir: str | Path) -> list[tuple[str, state_mod.SessionState]]:
    state_dir = locate.state_dir(decisions_dir)
    if not state_dir.is_dir():
        return []
    sessions = []
    for path in sorted(state_dir.glob("*.json")):
        if path.name.endswith(".trigger.json"):
            continue  # hookrunner's cheap gating file (threshold.py), not a digest sidecar
        loaded = state_mod.load(path)
        if loaded is not None:
            sessions.append((loaded.digest.session_id, loaded))
    return sessions


def render_aggregate(entries: list[AggregatedEntry]) -> str:
    """Chronologically ordered by session, Decided/Rejected/Open within each --
    grouped, not flattened, so a session's own related decisions stay
    legible together while the document as a whole still reads in the order
    things happened. Every entry names its session and date via the group
    header above it.
    """
    if not entries:
        return "# Decision log\n\nNo recorded decisions were found in any session.\n"

    # dict preserves insertion order; `entries` arrives sorted chronologically,
    # so the first appearance of a session_id fixes that session's position.
    by_session: dict[str, list[AggregatedEntry]] = {}
    session_dates: dict[str, str | None] = {}
    session_titles: dict[str, str | None] = {}
    for a in entries:
        by_session.setdefault(a.session_id, []).append(a)
        session_dates.setdefault(a.session_id, a.session_date)
        session_titles.setdefault(a.session_id, a.session_title)

    out = ["# Decision log", "", f"Merged from {len(by_session)} session digest(s)."]
    for session_id, session_entries in by_session.items():
        date_label = session_dates.get(session_id) or "date unknown"
        title = session_titles.get(session_id)
        session_label = f"{title} (`{session_id}`)" if title else f"session `{session_id}`"
        out += ["", f"## {date_label} — {session_label}"]
        for section in SECTIONS:
            section_entries = [a for a in session_entries if a.entry.section == section]
            if not section_entries:
                continue
            out += ["", f"### {section.capitalize()}"]
            for a in section_entries:
                line = f"- **{a.entry.text}**"
                if a.entry.why:
                    line += f" — {a.entry.why}"
                out.append(line)

    return "\n".join(out) + "\n"
