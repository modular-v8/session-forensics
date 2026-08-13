# session-forensics

A running decision digest for coding sessions with Claude Code. While you
work, a short record of what was decided, what was rejected, and why is kept
continuously up to date at `.decisions/<session-id>.md`. One command later
merges every digest in a project into a single chronological decision log —
the actual point of this: writing a report on something built across dozens
of sessions, where the reasoning currently lives only in transcripts nobody
reopens.

> **Windows only, in v1.** Detachment, process handling and every path in this
> tool assume Windows 10+. It will not run correctly on macOS or Linux. See
> [out of scope](spec.md#out-of-scope).

## What's transmitted, and to whom

Two model providers are used, in this order:

- **Gemini** (primary)
- **OpenRouter** (fallback — only attempted if Gemini fails with a retryable
  error *and* an OpenRouter key is configured)

Both receive the same payload under the same rules.

**Sent:**
- Your own and the assistant's visible text, redacted, from only the turns
  since the last update
- Mechanical facts: tool names, call counts, file *paths* touched, tool
  failure counts
- Quoted selections from a small set of structural signals (a question you
  answered, a tool call you refused)
- Titles of decisions already recorded, so the model doesn't repeat itself

**Never sent:**
- File contents, raw command output, reasoning/thinking blocks
- Any text from a turn the transcript itself records as non-human — these
  are structurally absent from the payload, not filtered out of it
- Anything at all, if no provider key is configured, the per-session call cap
  has been reached, or the project has opted out (below) — in every one of
  those cases the digest still updates, from structured facts alone

**Redaction runs before the payload is built**, not after:
- Provider API key shapes, JWTs, PEM blocks, `KEY=value` lines, credentials
  embedded in URLs, and the generic `token:`/`secret:`/`password:` form are
  stripped before anything is sent
- This catches key-*shaped* text; it cannot catch a sentence that describes a
  secret without reproducing its shape — if a project might contain either,
  use the opt-out marker

## Opting a project out

Create a `.decisions-optout` file (empty, any content) at the repository
root. From then on, nothing is ever transmitted for that project — no network
call is attempted at all — and the digest is built from structured facts
alone, stating plainly that summarisation is disabled.

## Digests are never committed

`.decisions/` carries its own `.gitignore` (`*` / `!.gitignore`), written and
verified by the tool itself before anything else is written there.

- Digests contain your own prompts verbatim in places, and this project's own
  measured corpus includes sessions with sensitive content (job-application
  and financial material) in them.
- Committing them was rejected outright as a design option.

## Install

**Plugin (recommended):**
- Install this repository as a Claude Code plugin.
- `hooks/hooks.json` binds `Stop`, `SessionEnd` and `PreCompact` to the
  bundled hook runner via `${CLAUDE_PLUGIN_ROOT}` — nothing else to
  configure.

**Manual fallback:** add this to your project's `.claude/settings.local.json`
(or `~/.claude/settings.json` for every project), replacing the path with
wherever you've placed this repository:

```json
{
  "hooks": {
    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "python", "args": ["<repo-path>/hooks/run_hookrunner.py"], "timeout": 5}]}],
    "SessionEnd": [{"matcher": "", "hooks": [{"type": "command", "command": "python", "args": ["<repo-path>/hooks/run_hookrunner.py"], "timeout": 5}]}],
    "PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": "python", "args": ["<repo-path>/hooks/run_hookrunner.py"], "timeout": 5}]}]
  }
}
```

Either way, give it a provider key — two ways, pick either:

- **`.env` file (easiest):** create `.env` at your repository root —
  ```
  GEMINI_API_KEY=your-key-here
  ```
  Add `.env` to your `.gitignore` — the tool will warn (in `.decisions/forensics.log`,
  not loudly) if it looks like you haven't. No restart needed; the next hook
  fire picks it up.
- **A real, persistent OS environment variable** — `setx GEMINI_API_KEY
  "your-key-here"` on Windows, from a *new* terminal, then fully restart
  Claude Code (not just start a new conversation — environment variables are
  only inherited by processes started *after* they're set). A real
  environment variable always takes precedence over `.env` if both are
  present.

With no key from either source, the tool still runs, producing a
deterministic-only digest from structured facts — it never fails silently
or crashes for a missing key. Python 3.11+ on the `PATH` as `python` is the
only other requirement — standard library only, nothing to `pip install`
(the `.env` support above is a small parser this project wrote itself, not
`python-dotenv`).

## Using it

Nothing to run day to day: the digest updates on its own while you work.
Read `.decisions/<session-id>.md` whenever you want to check in on a session,
mid-session or after.

- **Across a whole project:**

  ```bash
  python -m session_forensics aggregate --out report-input.md
  ```

  Merges every session's digest into one chronologically ordered document,
  deduplicated, every entry naming its source session and date.

- **Recovery / manual run**, for a session the hooks missed, or to preview
  what would be sent without transmitting anything:

  ```bash
  python -m session_forensics digest <transcript-path> --dry-run   # preview only, no network call
  python -m session_forensics digest <transcript-path>              # real run
  ```

- The Claude Code skill bundled with this plugin (`SKILL.md`) reads digests
  and runs the aggregate on request — it never writes a digest and never
  calls a model itself.

## Threshold tuning

An update fires when either **4 turns** or **6,000 new characters** have
accumulated since the last one (`SF_TURN_THRESHOLD` / `SF_CHAR_THRESHOLD`),
or unconditionally on `SessionEnd`/`PreCompact`. Both are configurable via
environment variables.

- **Measured against five real sessions, left unchanged.** Before: 4 turns /
  6,000 characters (the original, untested starting values). After: the same
  values.
- Every real session measured fired correctly and grew correctly across
  repeated reads (a mid-session read covering 43 turns, then 244, then 324,
  after more work), with no sign of firing too often or too rarely.
- Nothing in the real data pushed either number in either direction —
  "measured and confirmed," not "measured and changed."
- **Recovery from a rate-limit failure doesn't wait for the normal
  threshold.** If an update fails with a retryable error (rate limit, quota,
  a provider's 5xx), the digest records it and retries on the very next
  `Stop`, unconditionally — not the next one that also happens to cross the
  threshold.
- Since `Stop` fires after every assistant turn, recovery from a rate limit
  typically happens within your next turn or two, not after another full
  threshold's worth of conversation.
- There's no internal sleep-and-retry loop doing this: it's a small
  per-session flag that forces the next check to fire regardless of
  threshold, cleared again the moment an update actually succeeds.
- If `Stop` doesn't fire for a while (e.g. Claude is mid-tool-use and hasn't
  yielded a turn back yet), recovery waits for that, same as any other
  update would.

## Structural signals

Before a model is involved at all, four structural signals are detected
directly from transcript fields — these read a field and cannot be wrong, so
they're used as a deterministic fallback whenever no provider is available
(no key, cap reached, or opted out):

| Signal | What it catches | Fires (of 26 corpus transcripts) | Per 1,000 human messages |
|---|---|---|---|
| Question answered | An `AskUserQuestion` call and the choice made | 60, in 18 transcripts | 296 |
| Interrupted | A turn recorded as interrupted (field, with a text-marker fallback) | 10, in 7 transcripts | 39 |
| Tool call refused | The user explicitly rejected a tool call | 7, in 7 transcripts | 34 |
| Published externally | A local file pushed to a public artifact URL | 3, in **1** transcript | 15 |

- The last one is genuinely rare — it only fires in a session that publishes
  a file to an external URL, which most sessions never do.
- Three other signals were measured during development and found real but
  too narrow to carry alone: a parameter reversal (e.g. "increase the cap
  from 15 to 20"), a wholesale file rewrite, and a short reply after a long
  turn. The model now covers what they attempted, from prose, more
  completely.
- Full measurement record, including what was cut and why:
  [`docs/signals.md`](docs/signals.md).

## Known limitations

- **Aggregate deduplication is exact-text only.** Two sessions independently
  recording the same decision in different words are not recognised as the
  same entry. Measured directly across the 26-transcript corpus: 2 clusters
  of near-duplicates, about 5 entries out of 58, that a human reader would
  merge and the tool does not.
- **Reversals within a single update are not always narrated.** A number or
  approach that changes mid-delta sometimes lands in the digest as only its
  final value, without stating what it replaced. See
  [`VERIFICATION.md`](VERIFICATION.md) rule 1.
- **Validation scope is one person, one machine, one Claude Code version.**
  Every measurement in `docs/signals.md` and this README comes from that.
- **Model names and rate limits drift.** The tool targets
  `gemini-flash-latest`, the provider's own always-current alias, rather than
  a pinned version string — it currently resolves to `gemini-3.6-flash` and
  will resolve to something else later. Check
  `https://ai.dev/rate-limit` for your account's current numbers rather than
  trusting a hardcoded figure here.

## For contributors

- [`spec.md`](spec.md), [`plan.md`](plan.md) and [`tasks.md`](tasks.md) are
  the full design record — outcome, requirements, architecture, decisions
  and the task-by-task build log, including what was measured and what
  changed as a result.
- [`docs/signals.md`](docs/signals.md) is the measurement record the whole
  design rests on.
- [`VERIFICATION.md`](VERIFICATION.md) is a checklist for judging whether a
  digest can be trusted, grounded in real failures found while building
  this.
