"""The normalised event every stage downstream of the adapter operates on."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = ["Kind", "Event", "Transcript"]


class Kind(Enum):
    HUMAN_TEXT = "human_text"
    ASSISTANT_TEXT = "assistant_text"
    INJECTED = "injected"
    REASONING = "reasoning"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    META = "meta"


@dataclass(frozen=True)
class Event:
    index: int
    kind: Kind
    #: Populated only for HUMAN_TEXT and ASSISTANT_TEXT. Left None on every other
    #: kind so that quoting reasoning or injected content is impossible rather
    #: than merely forbidden.
    text: str | None = None
    timestamp: str | None = None
    tool_name: str | None = None
    tool_input: dict = field(default_factory=dict)
    tool_ok: bool | None = None
    injected_as: str | None = None
    #: Set only on the result of a question tool. That payload is the human's own
    #: selection, so it is quotable for the same reason a typed message is -- but
    #: it arrives as a tool result, so it gets a named field rather than being
    #: smuggled into `text` and loosening the invariant above.
    answer_text: str | None = None
    #: True when the transcript records the turn as human, False when it records
    #: it as something else, None when it carries no authorship field.
    turn_human: bool | None = None
    authorship_inferred: bool = False

    @property
    def quotable(self) -> bool:
        return self.text is not None


@dataclass
class Transcript:
    """A parsed session: events plus the facts that live on records, not messages."""

    events: list[Event] = field(default_factory=list)
    session_id: str | None = None
    branch: str | None = None
    cwd: str | None = None
    started: str | None = None
    ended: str | None = None
    lines: int = 0
    unparseable: int = 0
    record_types: dict[str, int] = field(default_factory=dict)
    #: (index, cumulative_dropped_tokens, pre_tokens, trigger)
    compactions: list[tuple[int, int, int, str]] = field(default_factory=list)
    denials: list[tuple[int, str]] = field(default_factory=list)
    interrupts: list[int] = field(default_factory=list)
    publications: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def dropped_tokens(self) -> int:
        """Maximum, never the sum -- the underlying figure is already cumulative."""
        return max((c[1] for c in self.compactions), default=0)
