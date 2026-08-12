"""Mechanical facts derived from the event stream.

Nothing here reads file contents or command output. Tool payloads are consumed to
produce counts, paths and exit states, then discarded -- which is why "no file
contents in the summary" is a property of the data flow rather than a filter
somebody has to remember to apply.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..transcript.events import Event, Kind, Transcript

__all__ = ["Facts", "extract"]

_WRITE_TOOLS = {"Write", "NotebookEdit"}
_EDIT_TOOLS = {"Edit"}
_SHELL_TOOLS = {"Bash", "PowerShell"}


@dataclass
class Facts:
    tools: Counter = field(default_factory=Counter)
    files_written: Counter = field(default_factory=Counter)
    files_edited: Counter = field(default_factory=Counter)
    files_read: Counter = field(default_factory=Counter)
    tool_failures: int = 0
    tool_results: int = 0
    human_messages: int = 0
    human_chars: int = 0
    human_inferred: int = 0
    assistant_blocks: int = 0
    reasoning_blocks: int = 0
    injected: Counter = field(default_factory=Counter)

    @property
    def failure_rate(self) -> float:
        return self.tool_failures / self.tool_results if self.tool_results else 0.0

    @property
    def touched(self) -> int:
        return len(set(self.files_written) | set(self.files_edited))

    def composition(self) -> str:
        """Coarse session shape, from tool composition only.

        Error rate, revert count, tools-per-text ratio and lexical profile were each
        measured across four transcripts and none of them discriminates. Tool
        composition is what is left.
        """
        edits = sum(v for k, v in self.tools.items() if k in _EDIT_TOOLS | _WRITE_TOOLS)
        shell = sum(v for k, v in self.tools.items() if k in _SHELL_TOOLS)
        browse = sum(v for k, v in self.tools.items() if "browser" in k.lower() or "chrome" in k.lower())
        total = max(1, edits + shell + browse)
        if browse / total > 0.4:
            return "browsing"
        if edits / total > 0.5:
            return "authoring"
        if shell / total > 0.5:
            return "shell-driven"
        return "mixed"


def extract(transcript: Transcript) -> Facts:
    facts = Facts()
    for event in transcript.events:
        if event.kind is Kind.TOOL_USE:
            facts.tools[event.tool_name or "?"] += 1
            _record_path(facts, event)
        elif event.kind is Kind.TOOL_RESULT:
            facts.tool_results += 1
            if event.tool_ok is False:
                facts.tool_failures += 1
        elif event.kind is Kind.HUMAN_TEXT:
            facts.human_messages += 1
            facts.human_chars += len(event.text or "")
            facts.human_inferred += int(event.authorship_inferred)
        elif event.kind is Kind.ASSISTANT_TEXT:
            facts.assistant_blocks += 1
        elif event.kind is Kind.REASONING:
            facts.reasoning_blocks += 1
        elif event.kind is Kind.INJECTED:
            facts.injected[event.injected_as or "?"] += 1
    return facts


def _record_path(facts: Facts, event: Event) -> None:
    path = event.tool_input.get("file_path")
    if not path:
        return
    if event.tool_name in _WRITE_TOOLS:
        facts.files_written[path] += 1
    elif event.tool_name in _EDIT_TOOLS:
        facts.files_edited[path] += 1
    elif event.tool_name == "Read":
        facts.files_read[path] += 1
