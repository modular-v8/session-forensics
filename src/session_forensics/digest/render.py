"""Markdown rendering: Decided / Rejected / Open, a strapline, a footer.

Identical input produces byte-identical output -- every value shown here is a
field already stored on `Digest`; nothing calls `datetime.now()` or iterates a
`set` for display (sets are only ever `len()`-ed, never listed).

Three behaviours are carried over from the deleted pre-pivot renderer, earned by
reading its real output rather than rediscovered from scratch -- see tasks.md
T3.6: the mechanical strapline, the empty-state stance ("a result, not a gap"),
and compaction disclosure using the maximum dropped-token figure, never a sum.
Two are deliberately not carried over: individual file listings (counts belong
in the strapline; lists do not belong at all), and "nothing here was generated
by a language model" (true before, false now -- the footer says which model).
"""

from __future__ import annotations

import datetime

from ..extract.facts import Facts
from .model import Digest, Entry

__all__ = ["render"]

_SECTION_TITLES = {"decided": "Decided", "rejected": "Rejected", "open": "Open"}


def render(digest: Digest) -> str:
    parts: list[str] = _header(digest) + ["", _strapline(digest)]

    if digest.optout:
        parts += ["", _OPTOUT_NOTICE]

    if digest.entries:
        for section in ("decided", "rejected", "open"):
            entries = digest.by_section(section)
            if not entries:
                continue
            parts += ["", f"## {_SECTION_TITLES[section]}", ""]
            parts += [_render_entry(e) for e in entries]
    else:
        parts += ["", _EMPTY_STATE]

    parts += ["", "---", "", _footer(digest)]

    return "\n".join(parts) + "\n"


def _header(digest: Digest) -> list[str]:
    """Claude Code's own session title (T4.14), when one exists, leads the
    document -- the session id moves to a subtitle line rather than
    disappearing, since it is still the filename and the stable identifier
    everything else (state sidecar, lock, threshold file) is keyed on. A
    session too new to have a title yet (killed after a turn or two, before
    Claude Code assigns one) falls back to exactly the pre-T4.14 header.
    """
    if digest.title:
        return [f"# {digest.title}", f"_Session `{digest.session_id}`_"]
    return [f"# Session digest: `{digest.session_id}`"]


_EMPTY_STATE = (
    "No decisions were recorded in this session. That is a result, not a gap "
    "-- not every session produces one."
)

_OPTOUT_NOTICE = (
    "**Summarisation is disabled for this project** (`.decisions-optout` is "
    "present). Nothing was transmitted anywhere; this digest reflects "
    "structured facts only."
)


def _render_entry(entry: Entry) -> str:
    line = f"- **{entry.text}**"
    if entry.why:
        line += f" — {entry.why}"
    if entry.turns:
        line += f" _(turns {entry.turns[0]}-{entry.turns[1]})_"
    return line


def _strapline(digest: Digest) -> str:
    shape = Facts(tools=digest.tools).composition()
    article = "An" if shape[:1].lower() in "aeiou" else "A"
    duration = _format_duration(digest.session_started, digest.session_ended)
    duration_clause = f"over {duration}" if duration else "(duration unknown)"

    files_touched = len(digest.files_touched_in_cwd)
    outside = len(digest.files_touched_outside_cwd)
    files_clause = f"{files_touched} file{'s' if files_touched != 1 else ''} touched"
    if outside:
        files_clause += f" (+{outside} outside the working directory)"

    calls = sum(digest.tools.values())
    decisions = len(digest.entries)

    return (
        f"{article} **{shape}** session {duration_clause}: "
        f"{calls} tool call{'s' if calls != 1 else ''}, {files_clause}, "
        f"{decisions} decision{'s' if decisions != 1 else ''} recorded."
    )


def _format_duration(start: str | None, end: str | None) -> str | None:
    if not start or not end:
        return None
    t0, t1 = _parse_timestamp(start), _parse_timestamp(end)
    if t0 is None or t1 is None:
        return None
    minutes = int(max(0.0, (t1 - t0).total_seconds()) // 60)
    if minutes < 1:
        return "under a minute"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _parse_timestamp(value: str) -> datetime.datetime | None:
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            return datetime.datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _footer(digest: Digest) -> str:
    lines: list[str] = []

    if digest.optout:
        lines.append(f"_Covers {digest.turns_covered} turn(s). Last updated {digest.last_success or 'never'}._")
    else:
        usage = f"{digest.calls} call{'s' if digest.calls != 1 else ''}"
        if digest.model:
            usage += f" to `{digest.model}`"
        if digest.provider:
            usage += f" via {digest.provider}"
        usage += f", {digest.tokens_in:,} in / {digest.tokens_out:,} out tokens"
        lines.append(
            f"_{usage}. Covers {digest.turns_covered} turn(s). "
            f"Last updated {digest.last_success or 'never'}._"
        )

    if digest.branch and digest.branch != "HEAD":
        lines.append(f"_Branch: `{digest.branch}`._")

    if digest.turns_pending:
        reason = f" (reason: {digest.last_error})" if digest.last_error else ""
        lines.append(
            f"_{digest.turns_pending} turn(s) unprocessed since the last "
            f"successful update{reason}. Will retry on the next trigger._"
        )

    if digest.cap_reached:
        lines.append(
            "_The per-session API call cap was reached; this digest continues "
            "updating from structured facts alone._"
        )

    if digest.no_key:
        lines.append(
            "_No provider key is configured (`GEMINI_API_KEY` / "
            "`OPENROUTER_API_KEY`); this digest reflects structured facts alone._"
        )

    if digest.compaction_count:
        lines.append(
            f"_This session was compacted {digest.compaction_count} time"
            f"{'s' if digest.compaction_count != 1 else ''}, dropping "
            f"{digest.dropped_tokens:,} tokens. Anything discussed before the "
            f"first boundary survives only as a summary, not as a record._"
        )

    if digest.unparseable_lines:
        lines.append(
            f"_{digest.unparseable_lines} transcript line(s) could not be "
            f"parsed and were skipped._"
        )

    if digest.dropped_entries:
        lines.append(
            f"_{digest.dropped_entries} entr{'y' if digest.dropped_entries == 1 else 'ies'} "
            f"dropped after a section reached its cap._"
        )

    return "\n".join(lines)
