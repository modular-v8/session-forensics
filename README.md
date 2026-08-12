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

Two model providers are used, in this order: **Gemini** (primary) and
**OpenRouter** (fallback, only attempted if Gemini fails with a retryable
error *and* an OpenRouter key is configured). Both receive the same payload
under the same rules.

**Sent:** your own and the assistant's visible text, redacted, from only the
turns since the last update; mechanical facts (tool names, call counts, file
*paths* touched, tool failure counts); quoted selections from a small set of
structural signals (a question you answered, a tool call you refused); the
titles of decisions already recorded, so the model doesn't repeat itself.

**Never sent:** file contents, raw command output, reasoning/thinking blocks,
or any text from a turn the transcript itself records as non-human — these
are structurally absent from the payload, not filtered out of it. Nothing is
sent at all if no provider key is configured, if the per-session call cap has
been reached, or if the project has opted out (below) — in every one of those
cases the digest still updates, from structured facts alone.

**Redaction runs before the payload is built**, not after: provider API key
shapes, JWTs, PEM blocks, `KEY=value` lines, credentials embedded in URLs, and
the generic `token:`/`secret:`/`password:` form are stripped before anything
is sent. This catches key-*shaped* text; it cannot catch a sentence that
describes a secret without reproducing its shape. If a project might contain
either, use the opt-out marker.

## Opting a project out

Create a `.decisions-optout` file (empty, any content) at the repository
root. From then on, nothing is ever transmitted for that project — no network
call is attempted at all — and the digest is built from structured facts
alone, stating plainly that summarisation is disabled.

## Digests are never committed

`.decisions/` carries its own `.gitignore` (`*` / `!.gitignore`), written and
verified by the tool itself before anything else is written there. Digests
contain your own prompts verbatim in places, and this project's own measured
corpus includes sessions with job-application and financial content in them —
committing them was rejected outright as a design option.

## Install

**Plugin (recommended):** install this repository as a Claude Code plugin.
`hooks/hooks.json` binds `Stop`, `SessionEnd` and `PreCompact` to the bundled
hook runner via `${CLAUDE_PLUGIN_ROOT}`; nothing else to configure.

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

Either way, set `GEMINI_API_KEY` (and optionally `OPENROUTER_API_KEY`) as a
real, persistent environment variable — not just for one terminal session —
so the detached worker process can see it. With no key set, the tool still
runs, producing a deterministic-only digest from structured facts.

Python 3.11+ on the `PATH` as `python` is the only other requirement —
standard library only, nothing to `pip install`.

## Using it

Nothing to run day to day: the digest updates on its own while you work.
Read `.decisions/<session-id>.md` whenever you want to check in on a session,
mid-session or after.

**Across a whole project:**

```bash
python -m session_forensics aggregate --out report-input.md
```

Merges every session's digest into one chronologically ordered document,
deduplicated, every entry naming its source session and date.

**Recovery / manual run**, for a session the hooks missed, or to preview what
would be sent without transmitting anything:

```bash
python -m session_forensics digest <transcript-path> --dry-run   # preview only, no network call
python -m session_forensics digest <transcript-path>              # real run
```

The Claude Code skill bundled with this plugin (`SKILL.md`) reads digests and
runs the aggregate on request — it never writes a digest and never calls a
model itself.

## Cost, call counts, and the daily-allowance arithmetic

Measured across five real sessions (real Gemini calls, `gemini-flash-latest`,
differing lengths — a 16-minute session up to a 141-hour one):

| Session | Calls | Tokens in/out | $ cost |
|---|---|---|---|
| Cleaner-Agent (141h 38m) | 10 | 21,202 / 2,717 | $0 |
| Personal-Finance-Tracker (3h 19m) | 6 | 14,739 / 1,052 | $0 |
| small (16m) | 1 | 1,285 / 323 | $0 |
| medium | 0 *(quota, see below)* | 0 / 0 | $0 |
| large | 0 *(quota, see below)* | 0 / 0 | $0 |

Every call/token figure is read directly from the provider's response body,
never estimated. **Cost is $0 across all five** because the key used
throughout this project's own measurement runs on Gemini's free tier —
confirmed directly from the metric name in real rate-limit errors
(`generate_content_free_tier_requests`). The free tier has no per-token
charge; its constraint is request rate, not spend.

That constraint is real and was hit directly during measurement: running
three replay sessions back-to-back produced
`QuotaExhausted... limit: 20, model: gemini-3.6-flash`, with `retry-after`
values of 37.5s, 2.8s and 45.7s across three separate real responses. Every
one of those is comfortably sub-minute — a daily quota resetting at UTC
midnight would report a wait in the thousands of seconds, not tens. That
makes `limit: 20` a **short, rolling per-minute-scale window**, not a daily
cap, and it only bound here because the replay tool used for measurement
(`run_over_transcript`, the CLI backtesting path — not the live hook) can
fire calls faster than a real session ever does.

The arithmetic this section exists to state: `SF_CALL_CAP` (25) is a
per-session ceiling, and real sessions above used a small fraction of it (1,
6, 10 calls). In live usage, a call only happens when a real `Stop` /
`SessionEnd` / `PreCompact` event has crossed `SF_TURN_THRESHOLD` or
`SF_CHAR_THRESHOLD` — which takes several actual turns of a person typing,
thinking and waiting on tools, never sub-3-second spacing. At 1–4 substantial
sessions in a day, that's roughly 6–40 realistic calls/day for one
developer, against a hard per-session cap of 25 and a directly-observed
short-window limit of 20 that ordinary, human-paced usage cannot plausibly
cluster into. A specific daily-allowance number is deliberately not quoted
here: this project already shipped one stale, training-knowledge-sourced
claim about this exact model family that turned out to be wrong once
checked against a live account (see Known limitations), and the model line
has already moved past that point once during this project's own lifetime.
If you need to tune against your own account's actual daily ceiling, read it
from `https://ai.dev/rate-limit` — the same URL the tool's own error
messages point to — rather than trusting a number here that could go stale
the same way.

## Threshold tuning

An update fires when either **4 turns** or **6,000 new characters** have
accumulated since the last one (`SF_TURN_THRESHOLD` / `SF_CHAR_THRESHOLD`),
or unconditionally on `SessionEnd`/`PreCompact`. Both are configurable via
environment variables.

**Measured against five real sessions and left unchanged** — before:
4 turns / 6,000 characters (the original, untested starting values). After:
the same values. Every real session measured fired correctly and grew
correctly across repeated reads (a mid-session read covering 43 turns, a
later read of the same session covering 244, then 324, after more work), with
no sign of firing too often or too rarely. There was nothing in the real data
pushing either number in either direction, so "measured and confirmed" is
the honest result here, not "measured and changed."

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

The last one is genuinely rare — it only fires in a session that publishes a
file to an external URL, which most sessions never do. Three other signals
were measured during development (a parameter reversal like "increase the
cap from 15 to 20"; a wholesale file rewrite; a short reply after a long
turn) and found real but too narrow to carry alone; the model now covers
what they attempted, from prose, more completely. Full measurement record,
including what was cut and why: [`docs/signals.md`](docs/signals.md).

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
- **Model names and rate limits drift, and this project already got burned by
  it once.** An earlier hardcoded model name stopped resolving entirely
  partway through building this and calls hung until timeout instead of
  failing cleanly — fixed by switching to `gemini-flash-latest`, the
  provider's own always-current alias, rather than a version string. That
  alias currently resolves to `gemini-3.6-flash`; it will resolve to
  something else later. The rate-limit figures in this README are real
  measurements taken on that day, not a promise about any other day — check
  `https://ai.dev/rate-limit` for your account's current numbers rather than
  trusting a hardcoded figure here.

## For contributors

[`spec.md`](spec.md), [`plan.md`](plan.md) and [`tasks.md`](tasks.md) are the
full design record — outcome, requirements, architecture, decisions and the
task-by-task build log, including what was measured and what changed as a
result. [`docs/signals.md`](docs/signals.md) is the measurement record the
whole design rests on. [`VERIFICATION.md`](VERIFICATION.md) is a checklist
for judging whether a digest can be trusted, grounded in real failures found
while building this.
