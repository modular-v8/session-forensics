# Plan: session-forensics

## Approach Summary

Claude Code fires a hook after every assistant turn. That hook does almost nothing: it reads a checkpoint file, decides whether enough new material has accumulated, and if so spawns a detached Windows process before exiting inside a second. The detached worker streams the transcript from the checkpoint forward, resolves who actually wrote each block, reduces the new material to a small redacted payload, and asks a model for **new digest entries only** — never a rewrite of what already exists. Returned entries are appended, capped, and rendered to `.decisions/<session-id>.md` in the repository. Because the digest is written continuously, no single trigger is load-bearing: a Ctrl+C or a crash costs at most the turns since the last update. An aggregate command merges every digest in a project into one chronological decision log, which is the artifact the whole thing exists to produce.

## Architecture

```
  Stop / SessionEnd / PreCompact          Command line
          |                          python -m session_forensics [digest|aggregate]
          v                                       |
   hookrunner.py                                  |
    - read stdin JSON                             |
    - read state sidecar  (cheap: one small file) |
    - below threshold? exit 0                     |
    - Popen(DETACHED_PROCESS) --.                 |
    - exit 0   (<1s, always)    |                 |
                                v                 v
                          worker.py <-------------'
                                |
   .-----------------------------------------------------------.
   |                          pipeline                          |
   |                                                            |
   |  transcript/  reader -> claude_code -> authorship          |
   |         |     (built; streams from checkpoint forward)     |
   |         v                                                  |
   |  extract/delta.py     new turns + structured facts         |
   |         |             (questions answered, refusals,       |
   |         |              interrupts, files, failures)        |
   |         v                                                  |
   |  redact.py            FAIL-CLOSED, runs BEFORE the         |
   |         |             payload exists                       |
   |         v                                                  |
   |  digest/prompt.py     payload + existing entry titles      |
   |         |                                                  |
   |         v                                                  |
   |  providers/           gemini -> openrouter on 429/5xx      |
   |         |             both normalise to (text, usage)      |
   |         v                                                  |
   |  digest/merge.py      append new entries, never rewrite    |
   |         |             existing ones; enforce caps in code  |
   |         v                                                  |
   |  digest/render.py     markdown                             |
   |         |                                                  |
   |         v                                                  |
   |  output/locate -> writer   .gitignore verified,            |
   |                            atomic write, checkpoint        |
   '-----------------------------------------------------------'
                                |
                                v
                  <repo>/.decisions/<session-id>.md
```

Four properties this shape protects:

**The hook path stays trivial.** `hookrunner.py` imports nothing from the pipeline — it reads stdin, reads one small JSON file, and either exits or spawns. It runs after every assistant turn on a path the user is waiting on, so it must be impossible for a parser bug or a slow network to touch it.

**Redaction precedes payload construction.** It is not a filter applied to output. The strings that would leave the machine are cleaned while the payload is assembled, and a redaction failure aborts the update rather than degrading to sending raw text.

**The checkpoint advances only after a successful write.** Every failure mode — network, provider, parse, disk — leaves the checkpoint where it was, so the next trigger retries the same material with more added. Nothing is lost, only delayed.

**Providers sit behind one interface.** `worker.py` calls `summarise(payload) -> Completion` and knows nothing about request shapes. Adding a third provider is a file.

## Tech Stack & Key Decisions

`spec.md` fixed the language, platform, dependency rule, provider order, output location and update cadence. This table decides what it left open.

| Decision | Choice | Why |
|---|---|---|
| Threshold check cost | `hookrunner` reads only the state sidecar, never the transcript | It runs every turn. Opening a 7 MB transcript to decide "not yet" would put the cost on the user's critical path. |
| Update trigger | `turns_since_update >= 4` **or** `new_chars >= 6000`; always on SessionEnd/PreCompact | Roughly 15–30 calls for a session the size of this project's own. Both numbers are guesses and flagged as such — first thing to measure. |
| Model output format | Strict JSON array of `{section, text, why, turns}` | Cheap models follow a small schema far more reliably than prose formatting, and a parse failure becomes a clean provider failure rather than a malformed digest. |
| Parse failure handling | Treated as provider failure — no fallback attempt, checkpoint unchanged | A malformed response means the prompt or the model is wrong; the other provider would fail the same way. |
| Entry identity | SHA-1 of the lower-cased, punctuation-stripped entry text | Deduplication needs to survive re-summarisation of overlapping material. Cheap, deterministic, no model involved. |
| Caps | Decided ≤ 12, Rejected ≤ 8, Open ≤ 5; 25 words per entry | Enforced by truncation in `merge.py` after parsing, so a model that ignores the instruction cannot produce a wall of text. |
| Cap overflow | Oldest entries win; new ones dropped with a count in the footer | A digest that silently reorders itself as a session grows is not readable as a record. |
| Session-end consolidation | One extra call on SessionEnd that may merge or supersede entries | The only point where rewriting existing entries is allowed. Bounds drift without paying for it on every update. |
| Call cap default | 25 per session | Chosen against the primary provider's daily allowance rather than token price — see `spec.md` § risks. Must be re-checked whenever either number changes. |
| Provider timeouts | 20s connect+read, no in-request retries | The next trigger retries anyway. Retrying inside a detached worker only lengthens the window where two workers could overlap. |
| Concurrency | Lock file in `.decisions/.state/`; a second worker for the same session exits immediately | `Stop` can fire again while a worker is still running. Without this, two workers race on the same digest and checkpoint. |
| Opt-out marker | `.decisions-optout` file at repo root | Visible, greppable, obvious in a directory listing, and cannot be missed the way a config key can. |
| Output directory ignoring | `.gitignore` inside `.decisions/` containing `*` and `!.gitignore` | Self-ignoring; needs no cooperation from the repo's root `.gitignore` and cannot be broken by editing it. |
| Repo root detection | Walk up from `cwd` for a `.git` entry; fall back to `cwd` | Hooks run from project root, the CLI may not. The self-ignoring directory makes the fallback safe. |
| Atomic write | `<name>.tmp` in the same directory, then `os.replace` | Same-volume rename is atomic on Windows, and `os.replace` overwrites where `os.rename` does not. |
| Detachment | `Popen(creationflags=DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP)`, stdio to `DEVNULL` | Stdlib, no shell, survives parent exit. `nohup`/`disown` is POSIX-only and unavailable here. |
| Package importability across the hook boundary (T4.8) | `hooks/run_hookrunner.py`: a tiny, import-free bootstrap script outside the `session_forensics` package that inserts `src/` onto `sys.path` before importing `hookrunner`. `hookrunner._spawn_worker` separately sets `PYTHONPATH` explicitly in the worker subprocess's environment, computed from its own `__file__`, rather than relying on inheritance. | `hookrunner.py` uses relative imports (`from . import threshold`), which only resolve via `python -m session_forensics.hookrunner` with `src/` on `PYTHONPATH` -- but a plugin hook command (`${CLAUDE_PLUGIN_ROOT}/hooks/...`) has no built-in way to set an env var for the process it launches, and `sys.path` is in-process state that does **not** propagate to a child process the way environment variables do. Verified directly: the full plugin chain (hooks.json → bootstrap → hookrunner → spawned worker → written digest) works end to end with `PYTHONPATH` completely absent from the environment at every step. |
| Model temperature (T3.3) | `0.2` on both adapters | Not pinned by the original decision table. This is factual extraction from a transcript, not creative writing -- consistency across many small calls in one session matters more than variety. Gemini also gets `responseMimeType: "application/json"` (cheap, well-supported); `responseSchema` is deliberately deferred until T3.9 shows whether parse failures are common enough to justify it -- this project's own rule is that a signal earns its place by firing on real data, not by seeming reasonable in advance. |
| Default model strings, corrected mid-T3.9 | `SF_MODEL_PRIMARY` default → `gemini-flash-latest`; `SF_MODEL_FALLBACK` default → `openai/gpt-5-mini` | The original defaults (`gemini-2.5-flash`, `openai/gpt-4o-mini`) reflected this tool's own training-cutoff knowledge, not the live catalog, and had already been superseded by real-world test time -- the stale Gemini name specifically made every real T3.9 call hang until timeout instead of failing cleanly (`NetworkError: read operation timed out`, diagnosed by testing raw DNS/TCP/HTTPS connectivity directly, which was fast and healthy, isolating the fault to the model name). `gemini-flash-latest` is Google's own alias, "hot-swapped with every new release" per ai.google.dev's model docs, chosen specifically so the default cannot go stale the same way again; `openai/gpt-5-mini` was confirmed live via OpenRouter's own `/api/v1/models` endpoint. |
| Daily-allowance thread, closed at T4.10 | Neither spec.md's original "~50/day" guess nor this table's own earlier "~1,500 RPD" third-party figure is carried forward. | Both were pre-measurement guesses about a number this project could actually observe. T4.10's five real sessions instead hit a **directly observed** limit: `QuotaExhausted`, `limit: 20`, with `retry-after` values of 37.5s/2.8s/45.7s across three separate real responses -- all sub-minute, which is the signature of a short rolling window (RPM-scale), not a daily reset (which would report a wait in the thousands of seconds). Neither original guess was about the right *kind* of limit, so "confirming" either would have meant asserting a number this project has no direct evidence for -- exactly the failure mode that produced the stale-model-name bug one row up, against a model line (`gemini-3.6-flash`) that has already moved past this tool's own training-cutoff knowledge once. README and tasks.md T4.10/T6.6 state the real figure, the reasoning that it's per-minute-scale rather than daily, and point to `https://ai.dev/rate-limit` as the live source of truth instead of hardcoding either guess. |
| Checkpoint streaming (T2.4) | `reader.read_records(after_line=)` and `claude_code.parse(after_line=, start_index=)` gained optional, default-`0` keyword parameters; every existing call site is unaffected. | tasks.md Phase 1 marks these two files "keep unchanged," but T2.4's acceptance requires a *measured* speedup for a late checkpoint, and the adapter-boundary rule ("only `claude_code.py`/`authorship.py` name Claude Code record fields") forbids re-implementing skip-ahead inside `delta.py`. Resolved by extending, not rewriting: default behaviour is byte-identical to before these parameters existed (verified against the Cleaner-Agent transcript — same event count, same candidate signals), and the new path is exercised only by `delta.py`. Measured 3.2x on a checkpoint 90% through the 2,454-line corpus transcript. |

## Data Model

Nothing persists to a database. Four shapes matter.

**`Entry`** — one digest line.

| Field | Type | Notes |
|---|---|---|
| `id` | str | SHA-1 of normalised `text`. The deduplication key. |
| `section` | `decided` \| `rejected` \| `open` | Anything else from the model is dropped. |
| `text` | str | The decision itself, truncated to the word cap. |
| `why` | str \| None | The reason. Absent is allowed; invented is not. |
| `turns` | tuple[int, int] | Transcript event range the entry was drawn from — the evidence pointer. |
| `added_at` | str | ISO timestamp of the update that produced it. |

**`Digest`** — `session_id`, `entries: list[Entry]`, plus footer counters: `calls`, `tokens_in`, `tokens_out`, `model`, `provider`, `turns_covered`, `turns_pending`, `last_success`, `last_error`, `cap_reached`, `optout`, `unparseable_lines`, `dropped_tokens`, and `dropped_entries` *(added at T3.5: the "oldest entries win" cap-overflow decision above requires a count in the footer, and this field was missing from the original list)*.

**`Delta`** — what one update sees: `turns` (redacted human and assistant text with event indices), `facts` (questions answered, refusals, interrupts, publications, files written/edited, failed commands, compaction), `existing_titles` (entry text only, so the model can avoid repeats), `range`. Plus `session_started`/`session_ended`/`branch` *(added at T3.6, since the render-time strapline needs whole-session duration and shape and there was no other place to source it without a second full parse)* — `session_started` is populated only when this delta happens to cover the transcript's first timestamped record (typically the first delta of a session and never again); `session_ended` is always the newest timestamp seen in *this* delta. `digest/merge.py::accumulate_session_stats` folds these into the digest's running totals each update.

**State sidecar** — `.decisions/.state/<session-id>.json`:

```json
{
  "session_id": "...",
  "checkpoint_event": 412,
  "checkpoint_line": 780,
  "tool_version": "0.2.0",
  "entries": [{"id": "a1b2...", "section": "decided", "text": "...", "why": "...", "turns": [408, 411], "added_at": "..."}],
  "calls": 7,
  "tokens_in": 18422,
  "tokens_out": 2106,
  "model": "gemini-2.5-flash",
  "provider": "gemini",
  "turns_covered": 94,
  "turns_pending": 0,
  "last_success": "2026-08-10T20:02:13Z",
  "last_error": null,
  "cap_reached": false,
  "optout": false,
  "no_key": false,
  "unparseable_lines": 0,
  "dropped_tokens": 0,
  "dropped_entries": 0,
  "tools": {"Edit": 41, "Write": 30},
  "files_touched_in_cwd": ["spec.md"],
  "files_touched_outside_cwd": ["C:/temp/scratch.json"],
  "session_started": "...",
  "session_ended": "...",
  "branch": "main",
  "compaction_count": 0
}
```

**This is the full, extended shape, not the illustrative subset originally sketched here** (`entry_ids`, a bare handful of counters). Discovered while building T3.6's render-time strapline: the rendered markdown is a derived view and is deliberately never parsed back (nothing else in this design reads its own output), so anything render.py needs across updates — tool composition, files touched, session timestamps, branch, compaction totals, and each existing entry's full text for the prompt's `existing_titles` — has nowhere else to live. `entry_ids` as a *separate* field was dropped: it is fully redundant with `entries[].id`, and keeping both would just be two copies that could disagree. `checkpoint_event` is what `delta.py` streams from. `calls` enforces the cap. Written by `output/state.py` (T4.3; not in the original module tree below, which listed only `locate.py`/`writer.py` under `output/`). Nothing here is human-facing — the markdown is.

## File / Module Structure

Modules marked **[built]** exist and survive the pivot unchanged.

```
session-forensics/
├── .claude-plugin/plugin.json
├── hooks/
│   ├── hooks.json                   Stop, SessionEnd, PreCompact
│   └── run_hookrunner.py            bootstrap: puts src/ on sys.path [T4.8]
├── bin/session-forensics.py         CLI bootstrap for plugin/skill contexts [T5.4]
├── SKILL.md                         read + aggregate only, never writes
├── src/session_forensics/
│   ├── __init__.py                  [built] __version__
│   ├── __main__.py                  [built]
│   ├── cli.py                       [built] + aggregate subcommand
│   ├── config.py                    env vars, thresholds, caps
│   ├── log.py                       size-capped, inside .decisions/
│   ├── optout.py                    .decisions-optout detection only [added T2.6]
│   ├── hookrunner.py                THIN. no pipeline imports. exit 0 always.
│   ├── worker.py                    detached orchestrator
│   ├── transcript/
│   │   ├── reader.py                [built] streaming
│   │   ├── events.py                [built] Event/Kind/Transcript
│   │   ├── authorship.py            [built] two-level, zero leakage
│   │   └── claude_code.py           [built] only agent-specific parser
│   ├── extract/
│   │   ├── facts.py                 [built] mechanical facts
│   │   ├── signals.py               [built] trimmed to the free ones
│   │   ├── heuristics.py            [built] A1/A4/A7/A8 only
│   │   └── delta.py                 checkpoint -> Delta
│   ├── redact.py                    fail-closed, pre-payload
│   ├── providers/
│   │   ├── base.py                  Completion; summarise() interface
│   │   ├── gemini.py                primary
│   │   └── openrouter.py            fallback
│   ├── digest/
│   │   ├── model.py                 Entry, Digest
│   │   ├── prompt.py                prompt construction + strict parsing
│   │   ├── merge.py                 append-only merge, dedupe, cap
│   │   └── render.py                markdown
│   ├── aggregate.py                 merge digests across a project
│   └── output/
│       ├── locate.py                repo root, .decisions/, gitignore verify
│       ├── writer.py                atomic write
│       ├── state.py                 state sidecar read/write [added T4.3]
│       └── lock.py                  worker lock [added T4.4]
├── tests/fixtures/smoke.jsonl
├── .github/workflows/ci.yml         windows-latest
├── docs/signals.md                  [built] measurement record
├── VERIFICATION.md
├── README.md
├── spec.md · plan.md · tasks.md
```

Three rules a coding agent must not break:

**`hookrunner.py` imports only `json`, `os`, `sys`, `subprocess`, `pathlib`, `config`, plus `threshold` and (transitively) `repo`.** Nothing from `transcript/`, `extract/`, `providers/` or `output/`. It runs on the user's critical path after every turn.

*Expanded at T4.6.* The original list had no way to satisfy "compare the transcript against the stored checkpoint" (spec.md § event-driven) without either opening the transcript (forbidden by this same file's acceptance line) or importing `output/state.py` (which pulls in `digest/model.py`, exactly the heavier pipeline this boundary exists to keep out). Resolved with two new, deliberately tiny modules: `repo.py` (just `repo_root()`, extracted out of `output/locate.py` so both sides of the boundary share one implementation) and `threshold.py` (a *separate* cheap counter file, `.decisions/.state/<session-id>.trigger.json`, tracking transcript byte-size via `os.stat()` — never opening it — and a fire-count that stands in for "turns since checkpoint," since `Stop` fires once per assistant turn by construction). This file is explicitly best-effort and never authoritative: worker.py's own checkpoint in `output/state.py` is untouched by it and is the only thing correctness depends on. See `threshold.py`'s module docstring for the full reasoning, including why it must never create `.decisions/` itself.

**`claude_code.py` and `authorship.py` are the only modules naming Claude Code record fields.** The `transcript/` package is the adapter boundary; a second agent is a sibling file.

**Nothing outside `providers/` knows a request shape.** `worker.py` sees `Completion(text, tokens_in, tokens_out, model, provider)`.

## Integration Plan

**Order.** Build against files first, network second, hooks last. The digest pipeline is fully exercisable from the CLI with a transcript path — that path stays the primary development loop and becomes the recovery tool for any session the hooks miss.

**Gemini (primary), OpenRouter (fallback).** Integrated together in the same phase, because a fallback added later is a fallback nobody has tested. Both adapters normalise to `Completion`. Local development needs neither: with no key present the pipeline produces a deterministic digest, which is also the opt-out path and the cap-exceeded path — one behaviour, three routes to it, so it gets exercised constantly rather than only in an edge case.

**Stubbing.** A `providers/base.py` fake that replays a canned JSON response makes merge, caps and rendering testable with no network and no key. That fake is also what CI uses, since CI must never make a paid call.

**Claude Code hooks.** Last. By then the only new variable is the trigger. `Stop` fires after every assistant turn, so the threshold logic gets exercised immediately and heavily on the first real session.

**The smoke fixture** must be hand-built: a small sanitised transcript containing at least one answered question, one refused tool call, and one interrupt, so CI exercises real paths. It may not be drawn from the personal-directory transcripts in the corpus — see `tasks.md` Phase 0's provenance rule.

## Security & Error Handling Strategy

No authentication or authorization surface: the tool runs as the user and reads files they own. The security work is entirely about what leaves the machine, and the bar rose when transmission replaced disk-writing as the risk.

**Three containment layers, in order.**

1. **Turn-level authorship.** Blocks belonging to a turn the transcript records as non-human are never transmitted. This catches harness-generated text that reads as ordinary prose — measured as one block in 322, undetectable by any pattern.
2. **Block-level classification.** Tool results, skill loads, compaction summaries, image stubs, editor context, command expansions and pasted files never reach the payload. Reasoning blocks and file contents are structurally absent: `Event.text` is `None` on those kinds, so transmitting one requires a code change rather than a missed filter.
3. **Pattern redaction.** Applied to every string entering the payload: provider key shapes, JWTs, PEM blocks, `KEY=value` env lines, `scheme://user:pass@host` URLs, and the generic `(api_key|secret|token|password|bearer): value` form. Matches become `[REDACTED:kind]` — the span, not the line.

**Redaction fails closed.** If `redact.py` raises, the update aborts and nothing is sent. A crash in the component preventing leaks must never degrade into sending raw text.

**The opt-out marker short-circuits before any payload is built**, not before the request is sent. A project that opted out never assembles transmittable text at all.

**The write gate.** No digest is written until `.decisions/` exists and its `.gitignore` has been written *and* read back with the expected content. Failure is a refusal, logged, exit 0.

**Failure surfacing differs by entry point, deliberately.** From a hook, everything goes to the log and the exit code is always 0 — a non-zero hook exit can make Claude Code report an error or stall. From the CLI, errors print to stderr and exit non-zero, because a human typed the command. Making these uniform is the most likely well-intentioned mistake.

**Every failure preserves the digest.** The checkpoint advances only after a successful atomic write, so a network error, a provider error, a parse failure or a crash leaves the last good digest intact and the same material queued for the next trigger. The footer records what failed and how many turns are pending, so a stale digest announces itself.

**Both entry points have a top-level catch** that logs the traceback and exits 0.

## Sequencing & Milestones

Phase 1 is complete — it was built during recon and survives the pivot. Everything after it is new.

| Phase | Delivers | Depends on | Gate |
|---|---|---|---|
| **0 — Recon** *(done)* | `docs/signals.md`; 26-transcript corpus measured | — | met |
| **1 — Transcript core** *(done)* | reader, events, authorship, claude_code, facts | 0 | met: 26/26 parse, 0.26 s slowest, zero authorship leakage |
| **2 — Delta + redaction** | `delta.py`, `redact.py`, `config.py`, opt-out marker | 1 | a payload from a secret-seeded transcript contains no unredacted match, checked on the request body |
| **3 — Model layer** | `providers/`, `prompt.py`, `merge.py`, `digest/render.py`, fake provider | 2 | a real transcript yields a capped, deduplicated digest; forced 429 falls back once; forced malformed response does not |
| **4 — Output + hooks** | `locate.py`, `writer.py`, state, lock, `hookrunner.py`, plugin, `hooks.json` | 3 | digest updates mid-session on a real run; Ctrl+C leaves a digest; `git status` clean |
| **5 — Aggregate + skill** | `aggregate.py`, `SKILL.md` | 4 | aggregate over the 26-transcript corpus produces one ordered document attributing every entry |
| **6 — Harden + ship** | CI, README, `VERIFICATION.md`, measured cost, public repo | 5 | every `spec.md` acceptance criterion checked |

**Phase 3 is where the product succeeds or fails.** Everything before it is plumbing that already works; everything after is delivery. If the digest entries are vague, the tool is worthless regardless of how reliably it triggers. Budget iteration on the prompt here, and validate against sessions whose decisions are already known — this project's own transcripts, where `docs/signals.md` records what actually happened.

**If Phase 5 slips, ship without the skill, not without the aggregate.** The aggregate is the stated deliverable; the skill is convenience.

**Do not tune thresholds before Phase 4.** The update trigger's values can only be judged against real sessions, and guessing them earlier wastes the measurement.

## Alternatives Considered

**Deterministic extraction alone.** Built, measured across 26 transcripts, rejected. Four of 26 sessions produced nothing; six heuristics were cut on evidence; one signal fired on 100% of errors. Structural signals reliably find that a question was answered and cannot find that someone changed their mind in prose. Full record in `docs/signals.md` — kept precisely so this is not re-attempted.

**Re-summarising the whole session on every update.** Rejected. Cost grows with session length, and repeatedly rewriting earlier entries lets detail drift silently. Append-only with one consolidation pass at session end bounds both.

**`SessionEnd` only.** Rejected. It does not fire on Ctrl+C, terminal close, or a crash — a multi-day trigger-matrix measurement was scheduled to quantify how bad this was. Updating during the session removes the question rather than answering it.

**`claude -p --model haiku` as transport.** Rejected. It boots a full Claude Code session per call — seconds, not milliseconds — and fires the tool's own hooks, requiring a recursion guard. Acceptable when the call happened once per session; not at 15–30.

**OpenRouter as primary.** Rejected on daily allowance. At this call volume its ceiling is exhausted in about two sessions, and a corpus written half by one model and half by another reads inconsistently once assembled into the report this exists to support.

**Sending structured facts only, no prose.** Rejected. Lowest exposure, but it strips exactly the reasoning the digest is meant to capture.

**Committing digests instead of ignoring them.** Rejected. They contain the user's own prompts, and the measured corpus includes job applications and financial records.

**A rolling project-level digest maintained by every session.** Deferred to v2. The aggregate command produces the same artifact on demand without cross-session write conflicts.

**A skill that can force a refresh.** Rejected. Two writers to one file is where idempotency bugs live. The hook writes; the skill reads.

## Open Risks Carried From Spec

**Resolved by this plan:** trigger reliability (continuous updates), diagnostics leaking (log inside the ignored directory), concurrent workers (lock file), provider coupling (adapter interface).

**Mitigated, still live:**

- *Incremental drift* — bounded by append-only plus a session-end consolidation pass. The consolidation prompt is unvalidated and is the most likely source of a bad digest.
- *In-repo output leaking* — self-ignoring directory, read-back verification, refusal to write when unverified. Residual: `git add -f`, or copying the directory elsewhere.
- *Transmission to third parties* — three containment layers plus a per-project opt-out. Redaction catches key-shaped strings, not a sentence describing something confidential.
- *Cost* — per-session call cap with deterministic fallback. The cap must be set against the primary's **daily** allowance, and that interaction needs re-checking whenever either number moves.

**Still open, by design:**

- *Threshold values* — 4 turns / 6,000 chars are guesses. First thing to measure in Phase 4.
- *Digest quality on small deltas* — a model given four turns may not distinguish a decision from a remark. Phase 3's real risk.
- *Aggregate deduplication* — whether two similarly worded decisions from different sessions are the same decision is a judgement the tool will sometimes get wrong.
- *Two provider schemas* — a provider changing its API breaks one path while the other keeps working, and the fallback is by definition the one nobody exercises.
- *Validation scope* — one user, one machine, Windows, one Claude Code version.
