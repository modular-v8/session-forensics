"""Candidate detection. Every candidate carries the evidence that produced it.

A candidate with an empty evidence list is a bug, not a low-confidence result.

Trimmed to A1, A4, A7, A8 -- the four that read a transcript field directly and
cannot be wrong. A2 (parameter reversal), A5 (rewrite-wholesale) and B2 (brief
reply after a long turn) were cut from here on the pivot: the model now covers
what they attempted, less badly, from prose rather than a narrow pattern. Their
measured fire rates stay in ``signals.SIGNALS`` as the historical record; see
docs/signals.md section 4b.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..transcript.events import Event, Kind, Transcript
from . import signals

__all__ = ["Evidence", "Candidate", "detect"]


@dataclass(frozen=True)
class Evidence:
    index: int
    kind: str          # "quote" | "fact"
    detail: str


@dataclass
class Candidate:
    signal: str
    title: str
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def tier(self) -> str:
        return signals.SIGNALS.get(self.signal, ("?",))[0]


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= signals.QUOTE_CAP else flat[:signals.QUOTE_CAP] + " [...]"


def detect(transcript: Transcript) -> list[Candidate]:
    events = transcript.events
    out: list[Candidate] = []
    out += _questions(events)
    out += _refusals(transcript)
    out += _interrupts(transcript)
    out += _publications(transcript)
    return out


#: The question tool echoes each question back alongside its answer. Quoting the
#: raw payload repeats the whole question before revealing the choice, so the
#: pairs are unpacked and only the selection is quoted.
_ANSWER_PAIR = re.compile(r'"(?P<q>(?:[^"\\]|\\.)*)"="(?P<a>(?:[^"\\]|\\.)*)"', re.S)


def _headline(text: str, limit: int = 80) -> str:
    """Clip on a word boundary. Titles cut mid-word read like corrupted output."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:flat.rfind(" ", 0, limit) or limit].rstrip(" ,;:—-") + "…"


def _questions(events: list[Event]) -> list[Candidate]:
    out = []
    for position, event in enumerate(events):
        if event.kind is not Kind.TOOL_USE or event.tool_name != "AskUserQuestion":
            continue
        headers = [str(q.get("header") or q.get("question", ""))
                   for q in (event.tool_input.get("questions") or []) if isinstance(q, dict)]
        payload = next((e.answer_text for e in events[position + 1:position + 4]
                        if e.kind is Kind.TOOL_RESULT and e.answer_text), None)
        pairs = _ANSWER_PAIR.findall(payload or "")

        evidence, chosen = [], []
        for index, (question, answer) in enumerate(pairs):
            label = headers[index] if index < len(headers) else _headline(question, 50)
            chosen.append(answer.strip())
            evidence.append(Evidence(event.index, "quote", f"**{label}** → {_clip(answer)}"))
        if not evidence:
            for question in headers:
                evidence.append(Evidence(event.index, "fact", f"asked: {_headline(question, 120)}"))

        if evidence:
            title = " · ".join(_headline(c, 45) for c in chosen[:3]) if chosen else "Question asked"
            out.append(Candidate("A1", title, evidence))
    return out


def _refusals(transcript: Transcript) -> list[Candidate]:
    return [Candidate("A8", "Tool call refused by the user",
                      [Evidence(index, "fact", f"denial recorded: {kind}")])
            for index, kind in transcript.denials]


def _interrupts(transcript: Transcript) -> list[Candidate]:
    return [Candidate("A4", "Action interrupted mid-flight",
                      [Evidence(index, "fact", "interrupt recorded on this turn")])
            for index in transcript.interrupts]


def _publications(transcript: Transcript) -> list[Candidate]:
    return [Candidate("A7", "File published to an external URL",
                      [Evidence(index, "fact", f"{path} -> {url}")])
            for index, path, url in transcript.publications]
