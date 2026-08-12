"""Signal definitions and their measured fire rates.

Every signal here fired on real transcripts before it was written down. Six others
were cut for failing that test and are listed at the bottom so nobody proposes them
again. Counts come from a 26-transcript corpus, 203 human messages -- see
docs/signals.md section 4b.

This dict is the full historical measurement record -- it still lists A2, A5 and
B2, which fired during recon but were cut from ``heuristics.py`` on the pivot (the
model covers what they attempted, less badly). Kept for the README's per-signal
fire-rate table and so nobody re-measures what is already known.
"""

from __future__ import annotations

__all__ = ["SIGNALS", "CUT", "QUOTE_CAP"]

#: Longest verbatim passage the renderer will emit. Bounds the damage from a wall
#: of pasted text -- including a credentials block -- landing in a summary.
QUOTE_CAP = 400

#: id -> (tier, human-readable name, corpus fires, transcripts fired in of 26)
SIGNALS = {
    "A1": ("A", "Question asked and answered", 60, 18),
    "B2": ("B", "Brief reply after a long turn", 31, 13),
    "A5": ("A", "File rewritten wholesale", 18, 9),
    "A4": ("A", "Action interrupted", 8, 7),
    "A8": ("A", "Tool call refused", 7, 7),
    "A2": ("A", "Parameter reversed", 4, 3),
    "A7": ("A", "File published externally", 3, 1),
}

#: Cut, with the evidence. Do not re-propose without new measurement.
CUT = {
    "A3": "fired on 100% of errors in all four hand-read transcripts -- an error list, not a signal",
    "A6": "edit-restores-prior-edit: 1 hit across 246 edits",
    "B1": "enumerated imperatives: tracks the user's writing mode, not the session",
    "B3": "message-after-tool-burst: fires on 48-85% of messages; discriminates nothing",
    "C*": "lexical move classes: 19/6/2/0 across four transcripts -- one session's phrasing",
    "kind-by-error-rate": "2.8% / 3.1% / 5.3% / 0% -- no ordering",
}
