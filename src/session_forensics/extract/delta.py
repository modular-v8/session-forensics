"""checkpoint -> Delta: the compact, redacted payload one update sees.

Streams from the checkpoint forward rather than re-parsing the whole transcript:
``claude_code.parse(path, after_line=checkpoint_line, start_index=checkpoint_event)``
skips JSON-parsing and event construction entirely for every line a previous
update already covered -- not just the expensive per-block work on top of it.
A checkpoint of ``(0, 0)`` is a fresh session and costs exactly what a full parse
costs, because that is what it is.

Because the skipped region is not touched at all, everything on the resulting
Transcript -- events, denials, interrupts, publications, compactions, lines,
unparseable -- describes only what is new. That is what this module wants:
mechanical facts about what changed, not a running total for the whole session.
The render-time strapline's running totals are a deliberately separate full
parse; see worker.py.

Every string that reaches a `Turn` or a candidate's evidence is redacted before
the `Delta` is constructed (spec.md: redaction precedes payload construction,
not a filter applied after). A `RedactionError` propagates out of `build_delta`
uncaught -- no `Delta` is ever returned half-cleaned.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..redact import redact
from ..transcript import claude_code
from ..transcript.events import Kind, Transcript
from . import heuristics
from .facts import Facts, extract as extract_facts

__all__ = ["Turn", "Delta", "build_delta"]


@dataclass(frozen=True)
class Turn:
    index: int
    role: str  # "human" | "assistant"
    text: str  # already redacted
    authorship_inferred: bool = False


@dataclass
class Delta:
    """What one update sees. Field names match plan.md's Data Model."""

    turns: list[Turn]
    facts: Facts
    #: A1/A4/A7/A8 candidates -- questions answered, interrupts, publications,
    #: refusals -- each already redacted at the evidence level.
    candidates: list[heuristics.Candidate] = field(default_factory=list)
    existing_titles: list[str] = field(default_factory=list)
    #: (checkpoint_event_resumed_from, last_event_index_reached) -- inclusive.
    #: The second value is the next update's checkpoint_event on success.
    range: tuple[int, int] = (0, 0)
    #: The next update's checkpoint_line on success.
    checkpoint_line: int = 0
    unparseable: int = 0
    #: (index, cumulative_dropped_tokens, pre_tokens, trigger) for compactions
    #: that happened inside this delta only.
    compactions: list[tuple[int, int, int, str]] = field(default_factory=list)
    #: Transcript-level metadata, populated when this delta happens to cover the
    #: record that carries it (session_started is typically only present on the
    #: very first delta of a session; session_ended reflects the newest
    #: timestamp seen in *this* delta). worker.py folds these into the digest's
    #: running totals -- see digest/merge.py::accumulate_session_stats. Added at
    #: T3.6 for the render-time strapline; not in the original Delta field list.
    session_started: str | None = None
    session_ended: str | None = None
    branch: str | None = None
    #: Claude Code's own session title, if this delta happens to cover a
    #: `custom-title`/`ai-title` record (T4.14). `custom_title` -- a title the
    #: user set themselves -- always wins over `ai_title` when both are
    #: present; see digest/merge.py::accumulate_session_stats for how these
    #: fold into the digest across incremental updates.
    ai_title: str | None = None
    custom_title: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.turns and not self.candidates


def build_delta(
    transcript_path: str,
    *,
    checkpoint_event: int = 0,
    checkpoint_line: int = 0,
    existing_titles: list[str] | None = None,
) -> Delta:
    """Build a `Delta` covering everything after `checkpoint_line` / `checkpoint_event`.

    Reasoning blocks, tool results and file contents never reach a `Turn`: they
    are structurally absent on the underlying `Event` (`Event.text is None` on
    those kinds), not filtered out here after the fact.
    """
    transcript = claude_code.parse(
        transcript_path, after_line=checkpoint_line, start_index=checkpoint_event
    )
    return _from_transcript(
        transcript,
        checkpoint_event=checkpoint_event,
        existing_titles=existing_titles,
    )


def _from_transcript(
    transcript: Transcript,
    *,
    checkpoint_event: int,
    existing_titles: list[str] | None,
) -> Delta:
    turns = [
        Turn(e.index, "human" if e.kind is Kind.HUMAN_TEXT else "assistant",
             redact(e.text), e.authorship_inferred)
        for e in transcript.events
        if e.kind in (Kind.HUMAN_TEXT, Kind.ASSISTANT_TEXT) and e.text
    ]

    candidates = heuristics.detect(transcript)
    for candidate in candidates:
        candidate.evidence = [
            heuristics.Evidence(ev.index, ev.kind, redact(ev.detail))
            for ev in candidate.evidence
        ]

    last_index = transcript.events[-1].index if transcript.events else checkpoint_event

    return Delta(
        turns=turns,
        facts=extract_facts(transcript),
        candidates=candidates,
        existing_titles=list(existing_titles or []),
        range=(checkpoint_event, last_index),
        checkpoint_line=transcript.lines,
        unparseable=transcript.unparseable,
        compactions=list(transcript.compactions),
        session_started=transcript.started,
        session_ended=transcript.ended,
        branch=transcript.branch,
        ai_title=transcript.ai_title,
        custom_title=transcript.custom_title,
    )
