"""Build the request from a `Delta`; parse a strict JSON array back.

The prompt asks for additions only, never a rewrite -- re-summarising the whole
session on every update would grow in cost and let earlier detail drift
silently (spec.md § prior decisions). The model sees the delta and the titles
already accepted, and returns only what is new.

Caps are mentioned here as guidance, not enforced here: spec.md is explicit that
output structure is enforced in code, not requested in a prompt, so
`digest/merge.py` truncates regardless of what the model was asked for. A
malformed or non-JSON response raises `providers.base.MalformedResponse` --
the same terminal, non-retryable error a transport-level failure would raise --
so `worker.py` has one failure shape to handle, not two.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .. import config
from ..extract.delta import Delta
from ..providers.base import MalformedResponse

__all__ = ["ParsedEntry", "build_prompt", "parse_entries"]

_VALID_SECTIONS = frozenset({"decided", "rejected", "open"})

_INSTRUCTIONS = """\
You maintain a running decision log for a coding session between a developer and \
a coding agent. Below are NEW conversation turns since the last update, some \
structural signals already detected in them, and the titles of decisions already \
recorded. Your job: extract ONLY new entries from the NEW turns -- decisions made, \
alternatives rejected, and points left open.

Three sections:
- "decided": a concrete choice that was made. What, and briefly why if the turns say why.
- "rejected": an alternative that was considered and explicitly turned down. What, and why.
- "open": a question, risk, or unresolved point the turns raise but do not settle.

Rules:
- Extract only what these turns actually show. A passing mention is not a decision. \
Never infer a decision from silence, and never invent a reason the text does not state.
- If something changes within these turns -- a number, an approach, a plan proposed \
then revised or reversed -- capture the change itself, not just where things ended up. \
Say what it was before and what it became. That shift is often the most useful thing \
this log can record, and the easiest thing to flatten into a single end-state entry.
- Do not repeat anything in "already recorded" below, even if phrased differently.
- Keep "text" to about {word_cap} words: the decision itself, not the discussion around it.
- Keep "why" short too, or omit it (null) if the turns do not state a reason.
- If nothing new qualifies, return an empty array: []
- Respond with ONLY a JSON array. No prose, no markdown code fences, no explanation \
before or after it.

Each array element:
{{"section": "decided" | "rejected" | "open", "text": "...", "why": "..." or null, \
"turns": [first_event_index, last_event_index]}}
"""


@dataclass(frozen=True)
class ParsedEntry:
    section: str
    text: str
    why: str | None
    turns: tuple[int, int] | None


def build_prompt(delta: Delta) -> str:
    """Render the full request text for one update. Every string on `delta` is
    already redacted (extract/delta.py) -- nothing here adds new raw content.
    """
    sections: list[str] = [_INSTRUCTIONS.format(word_cap=config.word_cap())]

    sections.append("Already recorded (do not repeat these):")
    if delta.existing_titles:
        sections.extend(f"- {title}" for title in delta.existing_titles)
    else:
        sections.append("(nothing recorded yet)")

    sections.append("\nStructural signals detected in this delta (evidence a decision "
                     "may be nearby -- confirm from the actual turn text, do not trust "
                     "the label alone):")
    if delta.candidates:
        for candidate in delta.candidates:
            sections.append(f"- [{candidate.signal}] {candidate.title}")
            for ev in candidate.evidence:
                sections.append(f"    ({ev.index}) {ev.detail}")
    else:
        sections.append("(none fired in this delta)")

    sections.append("\nNew turns:")
    if delta.turns:
        for turn in delta.turns:
            sections.append(f"[{turn.index}] {turn.role}: {turn.text}")
    else:
        sections.append("(no new human/assistant text in this delta -- decide only "
                         "from the structural signals and facts above, if anything)")

    f = delta.facts
    sections.append(
        f"\nMechanical facts for this delta: {sum(f.tools.values())} tool calls, "
        f"{f.touched} file(s) touched, {f.tool_failures} tool failure(s) of "
        f"{f.tool_results}, {f.human_messages} human message(s)."
    )

    return "\n".join(sections)


def parse_entries(raw_text: str, *, provider: str) -> list[ParsedEntry]:
    """Parse a provider's completion text into entries.

    Raises `MalformedResponse` if the response is not a JSON array (or a JSON
    object wrapping exactly one array, tolerated defensively -- some models add
    the wrapper despite instructions not to). Individual malformed *items*
    inside an otherwise-valid array are dropped, not coerced and not treated as
    a reason to fail the whole response -- one bad entry should not cost the
    others.
    """
    data = _load_json_array(raw_text, provider=provider)
    entries: list[ParsedEntry] = []
    for item in data:
        parsed = _parse_one(item)
        if parsed is not None:
            entries.append(parsed)
    return entries


def _load_json_array(raw_text: str, *, provider: str) -> list:
    text = _strip_code_fence(raw_text.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedResponse(f"response was not valid JSON: {exc}", provider=provider) from exc

    if isinstance(data, dict):
        # Defensive: tolerate {"entries": [...]} even though the prompt asks for
        # a bare array -- some models wrap it despite instructions.
        list_values = [v for v in data.values() if isinstance(v, list)]
        if len(list_values) == 1:
            data = list_values[0]

    if not isinstance(data, list):
        raise MalformedResponse(
            f"expected a JSON array, got {type(data).__name__}", provider=provider
        )
    return data


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    lines = lines[1:] if lines and lines[0].startswith("```") else lines
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_one(item) -> ParsedEntry | None:
    if not isinstance(item, dict):
        return None
    section = str(item.get("section", "")).strip().lower()
    if section not in _VALID_SECTIONS:
        return None
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    why_raw = item.get("why")
    why = why_raw.strip() if isinstance(why_raw, str) and why_raw.strip() else None
    return ParsedEntry(section=section, text=text, why=why, turns=_parse_turns(item.get("turns")))


def _parse_turns(value) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
