# Verification checklist

A checklist for judging whether a digest can be trusted, checkable against the
digest itself — none of these require re-opening the transcript. Every rule
here traces to something actually observed while building this tool, not a
hypothetical failure mode; the "traced from" line under each says where.

Run this against a digest whenever the stakes are high enough to matter — before
quoting it in a report, or after any change to `digest/prompt.py`.

## 1. A wide turn range on an entry — does it say what changed, or only where it landed?

If an entry cites a turn range spanning many turns (e.g. `(turns 29-31)` where
turns 29 and 31 are visibly far apart in the surrounding entries), check
whether its text names a *before* as well as an *after*. An entry that only
states a final value across a wide range may be flattening a reversal into a
single end-state — correct as far as it goes, but silently dropping the
"proposed → reversed → replaced" shape that is the most valuable thing this
tool can capture.

**Traced from T3.9**: validating against the Cleaner-Agent session, the
"complex tier" question cap was decided at 15, then revised to 20 within the
same delta (`docs/signals.md` § 4 calls this "the best turnaround in the
file"). The digest landed on the correct final value (20–25) but never stated
it had been 15. `digest/prompt.py`'s instructions were extended in response
("capture the change itself, not just where things ended up"); this rule is
the reader-side check for whenever that instruction doesn't fully land.

## 2. Does "Covers N turn(s)" ever go backwards across two reads of the same digest?

Read a digest, note the footer's turn count, read it again later in the same
session. That number must never decrease. If it does, the state sidecar and
the rendered file have gone out of sync — a bug, not a content question — and
should be reported rather than reasoned about content-wise.

**Traced from T4.9**: verified directly by killing a worker mid-write and
confirming the figure never regressed (244 → 324 across the interruption, never
downward) — the atomic write guarantee holding in practice, not just in the
unit-level test for it.

## 3. Does the footer's failure reason actually name the provider that failed?

If the footer reports a failure, check that the named provider is one whose
key you know *is* configured. A footer blaming the fallback provider (typically
OpenRouter) for a key that was never going to be present is very likely
masking the primary provider's real, different, more useful failure reason.

**Traced from T3.9**: exactly this happened during real validation. Every
early real-provider run failed with `AuthError: OPENROUTER_API_KEY is not
set` — but only Gemini was ever configured, so that fallback was never
supposed to run at all. The actual problem (Gemini silently timing out
against a stale model name) was invisible until `worker.py` was fixed to skip
a keyless fallback rather than attempt and report on it. If you see this
pattern in a footer from a build predating that fix, do not trust the stated
reason.

## 4. Is a short or empty digest actually a failure, or a correct result?

An empty Decided/Rejected/Open section, or the line "No decisions were
recorded in this session," is a valid, correct outcome for some sessions —
not evidence the tool broke. Before treating brevity as a bug, check whether
the session's own footer facts (tool calls, files touched) suggest genuinely
light or exploratory work.

**Traced from Phase 0 recon** (`docs/signals.md` § 4d): 4 of the 26 measured
corpus sessions produced zero structural signals, including one 4.5-hour,
127-tool-call session with nothing to report — a real, substantial session
that simply made no decisions worth recording. The empty state was
deliberately designed to read as a finding, not an error, for exactly this
reason.

## 5. Do the footer's mechanical counts look plausible for what you remember of the session?

Tool call count, files touched, and compaction token loss are all read
directly from the transcript, not summarised by a model — they should match
your own memory of the session's scale closely, not approximately.

**Traced from T3.9 and T5.3**: these figures were cross-checked against
`docs/signals.md`'s independently-recorded measurements four separate times
across two real sessions (143 and 191 tool calls; 228,999 and 145,968
compaction tokens dropped) and matched exactly every time. A mismatch here
points at a parsing or accounting bug, not a prose-quality question — check
`extract/facts.py` and `digest/merge.py::accumulate_session_stats`, not the
prompt.

## 6. Does anything in the digest look key-, token-, or credential-shaped?

A digest should never contain anything resembling `sk-...`, a JWT, a
`KEY=value` line, or credentials embedded in a URL. If it does, this is a
redaction failure, not a content-quality issue, and is serious: report it
immediately rather than editing it out and moving on.

**Traced from T2.3**: this is exactly the pattern class `redact.py`'s pattern
set targets, verified against crafted strings for every category before any
real transcript was ever processed. This rule exists because that guarantee
is upstream of everything else in this checklist — if it fails, none of the
other rules matter.

## 7. Garbled characters (mojibake) in the digest — a display problem, not a content problem

An em dash rendering as `�` or similar is a terminal/encoding display issue,
not evidence the underlying file is corrupt. Open the file directly (rather
than through a pipe or redirect) before concluding the content itself is
wrong.

**Traced from T3.9**: PowerShell's native-command handling turned a routine
informational message into a formatted `NativeCommandError` and — separately
— `>` redirection defaulted to an encoding that rendered UTF-8 content as
spaced-out mojibake in one PowerShell session while an identical command
produced clean output in another. Neither was a bug in the digest itself.
