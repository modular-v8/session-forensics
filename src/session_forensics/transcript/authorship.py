"""Two-level authorship resolution.

Turn level  -- did this turn originate from the human?   Read from transcript fields.
Block level -- may this text be quoted verbatim?         Decided by content catalogue.

These answer different questions and neither substitutes for the other. A single
human turn routinely carries both typed text and harness-attached content: an
editor context stub, a slash-command expansion, a pasted file. The turn is human;
those blocks are not quotable. Measured across 26 transcripts, every apparent
disagreement between the two levels was this distinction and not a misclassification.

See docs/signals.md sections 2 and 4b for the measurements behind every pattern here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

__all__ = ["TurnOrigin", "Authorship", "resolve", "resolve_turn", "classify_block"]


class TurnOrigin(Enum):
    """Where a turn came from, as recorded by the transcript itself."""

    HUMAN = "human"
    NOT_HUMAN = "not_human"
    UNKNOWN = "unknown"  # transcript carries no authorship field


#: `promptSource` values that mean a person put this text there.
#: `suggestion_accepted` counts: the human chose it, even if they did not type it.
#: `system` does not, and is the only defence against harness-generated prose that
#: carries no marker and no stylistic tell -- see docs/signals.md section 2.
HUMAN_PROMPT_SOURCES = frozenset({"typed", "suggestion_accepted"})

_IMAGE_STUB = re.compile(r"^\[Image: original \d+x\d+")
_SLASH_COMMAND = re.compile(r"^/[a-z][a-z0-9:_-]*\s*$")
_TAGGED = re.compile(r"^<([a-z][a-z0-9_-]*)")

_LOCAL_COMMAND_MARKERS = (
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "Caveat: The messages below were generated",
)

#: Tag names that identify a specific injected category. Anything else opening
#: with a tag is still non-quotable, just less specifically labelled.
_TAG_CATEGORIES = {
    "ide_opened_file": "ide_context",
    "ide_selection": "ide_context",
    "ide_diagnostics": "ide_context",
    "system-reminder": "system_reminder",
    "task-notification": "task_notification",
    "user-prompt-submit-hook": "hook_output",
}


def resolve_turn(record: dict) -> tuple[TurnOrigin, str | None]:
    """Turn-level origin, plus which field decided it.

    Returns ``(TurnOrigin.UNKNOWN, None)`` when the transcript predates these
    fields. Callers must surface that: authorship inferred from content alone
    cannot detect harness-generated text that reads as ordinary prose.
    """
    origin = record.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        kind = origin["kind"]
        decided = TurnOrigin.HUMAN if kind == "human" else TurnOrigin.NOT_HUMAN
        return decided, f"origin.kind={kind}"

    source = record.get("promptSource")
    if source:
        decided = TurnOrigin.HUMAN if source in HUMAN_PROMPT_SOURCES else TurnOrigin.NOT_HUMAN
        return decided, f"promptSource={source}"

    return TurnOrigin.UNKNOWN, None


def classify_block(text: str) -> str | None:
    """Injected category for a text block, or ``None`` if the block is quotable.

    Ordered most specific first; the trailing tag check is the catch-all so an
    unrecognised wrapper fails closed rather than being quoted.
    """
    if not text:
        return "empty"

    stripped = text.lstrip()
    head = text[:400]

    if text.startswith("Base directory"):
        return "skill_load"
    if text.startswith("This session is being continued"):
        return "compaction"
    if stripped.startswith("[Request interrupted"):
        return "interrupt"
    if _IMAGE_STUB.match(stripped):
        return "image_stub"
    if _SLASH_COMMAND.match(stripped):
        return "slash_command"
    if any(marker in head for marker in _LOCAL_COMMAND_MARKERS):
        return "local_command"

    tag = _TAGGED.match(stripped)
    if tag:
        name = tag.group(1)
        if name in _TAG_CATEGORIES:
            return _TAG_CATEGORIES[name]
        if name.endswith("-command"):
            return "command_expansion"
        # Pasted markup, unrecognised wrappers, attached documents.
        return "attached_content"

    return None


@dataclass(frozen=True)
class Authorship:
    """Both levels for one text block, plus whether it may be quoted."""

    turn: TurnOrigin
    turn_source: str | None
    block_category: str | None

    @property
    def quotable(self) -> bool:
        """Quotable only if the turn is not known to be non-human AND the block is clean.

        ``UNKNOWN`` turns are allowed through -- older transcripts would otherwise
        yield nothing -- which is exactly why ``authorship_inferred`` must be
        reported in the summary.
        """
        return self.turn is not TurnOrigin.NOT_HUMAN and self.block_category is None

    @property
    def counts_as_human_turn(self) -> bool:
        """Whether the turn participates in positional signals such as B2.

        Independent of ``quotable``: a turn whose only block is a pasted file is
        still a human turn, so the turn sequence stays intact for adjacency.
        """
        return self.turn is not TurnOrigin.NOT_HUMAN

    @property
    def authorship_inferred(self) -> bool:
        """True when no transcript field decided this, so the summary must say so."""
        return self.turn is TurnOrigin.UNKNOWN


def resolve(record: dict, text: str) -> Authorship:
    """Resolve both levels for one text block of one record."""
    turn, source = resolve_turn(record)
    return Authorship(turn=turn, turn_source=source, block_category=classify_block(text))
