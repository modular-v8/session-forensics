"""Claude Code transcript adapter.

Together with `authorship.py` this is the only place that knows what a Claude Code
record looks like. Everything downstream sees `Event` objects. A second agent's
adapter is a sibling file, not a change to anything below.

The record-type set is open-ended and version-dependent: four transcripts three
weeks apart produced fifteen distinct types and three different field sets. Nothing
here requires a field to exist, and any unrecognised record becomes META.
"""

from __future__ import annotations

from pathlib import Path

from .authorship import TurnOrigin, classify_block, resolve_turn
from .events import Event, Kind, Transcript
from .reader import read_records

__all__ = ["parse"]


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse(path: str | Path, *, after_line: int = 0, start_index: int = 0) -> Transcript:
    """Parse a transcript, optionally resuming from a checkpoint.

    ``after_line``/``start_index`` default to 0, which is a full parse from the
    start and byte-identical to this function's behaviour before these parameters
    existed. Passed together (as extract/delta.py does, from the state sidecar's
    ``checkpoint_line``/``checkpoint_event``) they skip every already-processed
    line entirely and resume event numbering where the previous parse left off,
    so evidence indices stay meaningful across updates. The returned
    ``Transcript`` is then scoped to the new region only -- ``events``,
    ``denials``, ``interrupts``, ``publications``, ``compactions``, ``lines`` and
    ``unparseable`` all describe what is new, not the session cumulatively.
    """
    out = Transcript()
    out.lines = after_line
    index = start_index
    pending_question = False

    for line_no, record in read_records(path, after_line=after_line):
        out.lines = line_no
        if record is None:
            out.unparseable += 1
            continue

        rtype = str(record.get("type"))
        out.record_types[rtype] = out.record_types.get(rtype, 0) + 1

        out.session_id = out.session_id or record.get("sessionId") or record.get("session_id")
        out.branch = out.branch or record.get("gitBranch")
        out.cwd = out.cwd or record.get("cwd")

        if rtype == "ai-title":
            out.ai_title = record.get("aiTitle") or out.ai_title
        elif rtype == "custom-title":
            out.custom_title = record.get("customTitle") or out.custom_title
        stamp = record.get("timestamp")
        if stamp:
            out.started = out.started or stamp
            out.ended = stamp

        if rtype == "frame-link":
            out.publications.append((index, str(record.get("path") or ""), str(record.get("frameUrl") or "")))
        if record.get("interruptedMessageId"):
            out.interrupts.append(index)

        # Only a user-initiated refusal is a decision. A permission-rule denial is
        # the harness applying configuration and records no choice anyone made.
        denial = record.get("toolDenialKind")
        if denial == "user-rejected":
            out.denials.append((index, str(denial)))

        meta = record.get("compactMetadata")
        if isinstance(meta, dict):
            out.compactions.append((
                index,
                _int(meta.get("cumulativeDroppedTokens")),
                _int(meta.get("preTokens")),
                str(meta.get("trigger") or "unknown"),
            ))

        message = record.get("message")
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        turn, _source = resolve_turn(record)
        content = message.get("content")
        blocks = ([{"type": "text", "text": content}] if isinstance(content, str)
                  else content if isinstance(content, list) else [])

        for block in blocks:
            if not isinstance(block, dict):
                continue
            index += 1
            btype = block.get("type")

            if btype == "text":
                text = block.get("text") or ""
                if role == "user":
                    event = _user_text(index, text, turn, stamp)
                    _interrupt_fallback(out, event)
                    out.events.append(event)
                else:
                    out.events.append(Event(index, Kind.ASSISTANT_TEXT, text=text, timestamp=stamp))
            elif btype == "thinking":
                out.events.append(Event(index, Kind.REASONING, timestamp=stamp))
            elif btype == "tool_use":
                name = block.get("name")
                pending_question = name == "AskUserQuestion"
                out.events.append(Event(index, Kind.TOOL_USE, timestamp=stamp,
                                        tool_name=name,
                                        tool_input=block.get("input") or {}))
            elif btype == "tool_result":
                answer = None
                if pending_question:
                    payload = block.get("content")
                    answer = payload if isinstance(payload, str) else None
                    pending_question = False
                out.events.append(Event(index, Kind.TOOL_RESULT, timestamp=stamp,
                                        tool_ok=not block.get("is_error"),
                                        answer_text=answer))
            else:
                out.events.append(Event(index, Kind.META, timestamp=stamp))

    return out


def _interrupt_fallback(out: Transcript, event: Event) -> None:
    """Older transcripts record an interrupt only as a text marker, not a field.

    The field is preferred where present; without this the signal silently
    under-counts on any transcript predating it.
    """
    if event.injected_as == "interrupt" and event.index not in out.interrupts:
        out.interrupts.append(event.index)


def _user_text(index: int, text: str, turn: TurnOrigin, stamp: str | None) -> Event:
    """Apply both authorship levels to one user-role text block."""
    category = classify_block(text)
    if turn is TurnOrigin.NOT_HUMAN:
        # The turn level overrides a clean-looking block: harness-generated prose
        # carries no marker the catalogue could ever match.
        return Event(index, Kind.INJECTED, timestamp=stamp,
                     injected_as=category or "non_human_turn", turn_human=False)
    if category is not None:
        return Event(index, Kind.INJECTED, timestamp=stamp,
                     injected_as=category, turn_human=turn is TurnOrigin.HUMAN or None)
    return Event(index, Kind.HUMAN_TEXT, text=text, timestamp=stamp,
                 turn_human=True if turn is TurnOrigin.HUMAN else None,
                 authorship_inferred=turn is TurnOrigin.UNKNOWN)
