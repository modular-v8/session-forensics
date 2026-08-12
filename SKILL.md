---
name: session-forensics
description: Read this project's running decision digest(s) under .decisions/, or merge every session's digest into one chronological decision log. Use when the user asks what was decided, rejected, or left open in this or a past session; wants a summary, changelog, or report of decisions across the project's history; or asks to see, combine, or export the decision log. Read-only -- never writes a digest and never calls a model provider.
---

# session-forensics: read and aggregate decision digests

This skill is **read-only**. It never writes to `.decisions/` and never calls
Gemini, OpenRouter, or any other model provider. The `Stop`/`SessionEnd`/
`PreCompact` hook is the *only* writer -- a second write path to the same
file is exactly where idempotency bugs live (plan.md § Alternatives
Considered). If asked to "refresh," "update," or "regenerate" a digest, explain
that this skill cannot do that -- the digest updates on its own during the
session -- and offer to read whatever is already there instead.

## What `.decisions/` contains

- `.decisions/<session-id>.md` -- one running digest per Claude Code session in
  this project, kept continuously up to date while that session runs. Three
  fixed sections (Decided, Rejected, Open), a one-line strapline, and a footer
  reporting call/token counts and staleness.
- `.decisions/.state/` -- machine state (checkpoints, lock files). Not
  human-facing; do not read or parse it for this skill's purposes.
- `.decisions/.gitignore` -- makes the whole directory self-ignoring. Digests
  are never committed: they carry the user's own prompts, and some contain
  personal or financial context.

A project that has never run a session, or where every session opted out
(`.decisions-optout` at the repo root), may have no `.decisions/` directory at
all, or one with only opt-out digests in it. Both are correct, unremarkable
states -- say so plainly rather than treating either as an error.

## Answering about one session

Read `.decisions/<session-id>.md` directly (a plain file read -- no command
needed). If the user means "this session" and you don't already know its id,
it is the current transcript's filename stem; if genuinely ambiguous, ask
rather than guessing which file they mean.

## Answering about the whole project -- a report, a changelog, "what have we decided so far"

Run the aggregate command. It merges every session's digest into one
chronologically ordered document, deduplicating repeated decisions and naming
the source session and date for every entry:

```
python "${CLAUDE_PLUGIN_ROOT}/bin/session-forensics.py" aggregate
```

Add `--out <path>` to write the merged document to a file instead of printing
it; add `--cwd <path>` if the project root isn't the current directory. This
command only reads existing digests and prints/writes the merge -- it does not
touch `.decisions/` itself.

If the merged output is empty, say so plainly (no sessions have recorded
decisions yet) rather than inventing content to fill the gap.

## What not to do

- Do not write, edit, or delete anything under `.decisions/`.
- Do not call a model provider on the user's behalf to "fill in" a thin or
  empty digest -- structural facts alone, or an empty section, are correct,
  recorded outcomes, not failures to compensate for.
- Do not parse `.decisions/.state/*.json` and present it as if it were digest
  content -- it is internal bookkeeping, not written for a reader.
