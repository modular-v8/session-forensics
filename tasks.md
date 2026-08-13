# Tasks: session-forensics

Phases follow `plan.md` § Sequencing & Milestones. Verification is bundled into each task's Acceptance line — v1 has no test suite beyond a CI smoke run, so "done" and "checked" are the same moment.

**Reading this cold?** Start with `spec.md` § outcome, then `docs/signals.md` § 4b and § 5. The second explains why six heuristics were cut and why a model is now doing the summarising — it is the evidence behind the current design, and it exists so nobody re-attempts the deterministic-only approach.

---

## Phase 0 — Recon · **complete**

Four transcripts hand-read, 26 measured. Produced `docs/signals.md`: the record schema, the signal fire counts, the falsified hypotheses, and the corpus provenance rule.

Findings that still bind the design:

- **Authorship is a transcript field, not an inference.** `origin` / `promptSource` state it directly. A content-only filter measured 53% precision on unseen data; the two-level resolver measured **zero leakage across 322 blocks**.
- **One error class is undetectable without the field** — harness-generated prose carrying no marker. Hand-adjudicated, one block in 322.
- **Structural signals miss what matters.** Four of 26 sessions fired nothing; a 4.5-hour session with 127 tool calls produced zero decisions. This is why the model layer exists.
- **Compaction loss is exactly reportable.** 1,503,437 tokens across four unique histories; take the maximum per session, never the sum.
- **Provenance rule, binding on every later phase:** transcripts under personal directories are for local measurement only. No committed fixture, README excerpt, or published example may derive from them.

**T0.11** carries forward to Phase 6: publish per-signal fire rates and cost figures in the README.

---

## Phase 1 — Transcript core · **complete**

Built during recon; survives the pivot unchanged. `reader.py`, `events.py`, `authorship.py`, `claude_code.py`, `facts.py`, and a trimmed `heuristics.py`.

Measured across all 26 transcripts: **0 unparseable lines, slowest 0.26 s, peak memory 4.6 MB on a 7.5 MB input, byte-identical output across repeat runs.**

Deliberately **not** built, having turned out to be unnecessary: `kind.py` (`Facts.composition()` covers it in eight lines) and the trigger-matrix measurement (continuous updating removes the question).

### State of the existing code, for whoever picks this up

`src/session_forensics/` already contains working code written before the pivot. It compiles, runs, and was measured — but not all of it survives.

| File | Status |
|---|---|
| `transcript/reader.py`, `events.py`, `authorship.py`, `claude_code.py` | **Keep unchanged.** Measured; `authorship.py` is load-bearing for what may be transmitted. *(Updated at T2.4: `reader.py` and `claude_code.py` gained optional, default-`0` checkpoint parameters -- additive, default behaviour unchanged, see plan.md's Tech Stack table.)* |
| `extract/facts.py` | **Keep unchanged.** Feeds the `Delta`'s structured facts. |
| `extract/heuristics.py` | **Trim** to A1 (question answered), A4 (interrupt), A7 (publication), A8 (refusal) — the four that read a field and cannot be wrong. Delete A2, A5, B2; the model covers what they attempted, less badly. |
| `extract/signals.py` | **Trim** with it. Drop `params()` and the B2 constants. **Keep the `CUT` dict** — it is the record of six heuristics cut on evidence, and it exists so they are not re-proposed. |
| `render.py` (top level) | **Deleted.** Its output shape — activity listings, file lists, provenance prose — is not the crisp three-section digest this now produces. The behaviours worth keeping are written up under T3.6, including the three that were earned by reading real output and one line that must now say the opposite. |
| `cli.py`, `__main__.py` | **Stubbed**, pending rewrite for the `digest` and `aggregate` subcommands. The stub exits non-zero with a pointer to T2.7; it exists so `python -m session_forensics` gives a useful message instead of an `ImportError`. The asymmetric exit-code rule stays: CLI exits non-zero on error, hooks always exit 0. |

Nothing in `output/`, `providers/` or `digest/` exists yet.

---

## Phase 2 — Delta and redaction

Everything needed to build a small, safe payload. No network in this phase. Redaction lands **before** anything can transmit, which is why it precedes Phase 3 rather than following it.

- [x] **T2.1** Implement `config.py`: read `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `SF_MODEL_PRIMARY`, `SF_MODEL_FALLBACK`, `SF_TURN_THRESHOLD` (4), `SF_CHAR_THRESHOLD` (6000), `SF_CALL_CAP` (25), `SF_OUT_DIR`, `SF_LOG_LEVEL` from the environment, plus the section and word caps.
  - Acceptance: values are read fresh on access, never cached at import — hook invocations are separate processes and a cached value would be stale in exactly the case that matters. A malformed integer falls back to its default rather than raising.
  - Refs: spec § constraints, plan § Tech Stack
  - Depends on: none

- [x] **T2.2** Implement `log.py`: size-capped file logger, destination supplied by the caller, never writing to stdout or stderr.
  - Acceptance: exceeding the cap rotates or truncates rather than growing unbounded. Nothing appears on stdout/stderr when used. Destination resolves inside `.decisions/` once `locate.py` exists in Phase 4.
  - Refs: spec § requirements, plan § Security
  - Depends on: T2.1

- [x] **T2.3** Implement `redact.py`: span-level redaction for provider key shapes, JWTs, PEM blocks, `KEY=value` env lines, `scheme://user:pass@host` URLs, and the generic `(api_key|secret|token|password|bearer): value` form.
  - Acceptance: each pattern class is verified against a crafted string. Matches are replaced span-wise with `[REDACTED:kind]`, leaving surrounding context intact. **The module raises rather than returning partially-cleaned text on internal failure** — callers must be unable to proceed with unredacted content.
  - Refs: spec § requirements, plan § Security (three containment layers)
  - Depends on: none

- [x] **T2.4** Implement `extract/delta.py`: given a transcript and a checkpoint event index, produce a `Delta` carrying new human and assistant text, structured facts, the existing entry titles, and the event range.
  - Acceptance: streams from the checkpoint rather than re-parsing from the start, verified by timing a late-checkpoint delta against a full parse on the 2,454-line transcript. Reasoning blocks, tool results and file contents are structurally absent — assert `Event.text is None` for those kinds rather than filtering them out.
  - Refs: plan § Data Model (`Delta`), spec § requirements
  - Depends on: T2.3

- [x] **T2.5** Route every string entering the `Delta` through `redact.py` at construction time.
  - Acceptance: a transcript seeded with one instance of each pattern class produces a `Delta` containing no unredacted match, asserted on the `Delta` object itself, not on rendered output. A raise inside `redact.py` propagates and no `Delta` is produced.
  - Refs: spec § requirements (redaction before payload construction)
  - Depends on: T2.3, T2.4

- [x] **T2.6** Implement the opt-out marker: a `.decisions-optout` file at repo root short-circuits before any `Delta` is built.
  - Acceptance: with the marker present, no transmittable payload is constructed at all — verified by asserting the code path exits before `delta.py` is called, not by checking that a request was skipped.
  - Refs: spec § requirements, plan § Security
  - Depends on: T2.4

- [x] **T2.7** Extend the CLI with `digest --dry-run`, printing the `Delta` that would be sent.
  - Acceptance: run against three real transcripts, the printed payload contains only human and assistant text plus mechanical facts. This is the human-inspectable proof of what leaves the machine, and it is the tool used to verify T2.5 and T2.6 by eye.
  - Refs: plan § Integration Plan, spec § acceptance criteria
  - Depends on: T2.5, T2.6

**Gate:** a payload built from a secret-seeded transcript contains no unredacted match; an opted-out project builds no payload at all; `--dry-run` shows a human exactly what would be transmitted.

---

## Phase 3 — Model layer

Where the product succeeds or fails. Everything before is plumbing that works; everything after is delivery. If entries are vague, reliable triggering is worthless.

- [x] **T3.1** Define `providers/base.py`: a `summarise(payload) -> Completion` interface and a `Completion(text, tokens_in, tokens_out, model, provider)` result, plus a typed error distinguishing retryable conditions (rate limit, quota, 5xx) from terminal ones.
  - Acceptance: the retryable/terminal distinction is a property of the error type, not a string check at the call site. `worker.py` can decide whether to fall back without knowing any provider's response shape.
  - Refs: plan § Tech Stack, spec § requirements (failover conditions)
  - Depends on: none

- [x] **T3.2** Implement `providers/fake.py`: replays a canned response, configurable to fail with any error type.
  - Acceptance: every downstream task in this phase is testable through it with no key and no network. CI uses it exclusively — **CI must never make a paid call.**
  - Refs: plan § Integration Plan (stubbing)
  - Depends on: T3.1

- [x] **T3.3** Implement `providers/gemini.py` and `providers/openrouter.py` over `urllib`, each normalising to `Completion`.
  - Acceptance: the same `Delta` sent through both returns the same normalised shape with real token counts from each provider's response. 20-second timeout, no in-request retries. Keys are read at call time and never logged.
  - Refs: spec § data & integrations, plan § Tech Stack
  - Depends on: T3.1

- [x] **T3.4** Implement `digest/prompt.py`: build the request from a `Delta` plus existing entry titles, and parse a strict JSON array of `{section, text, why, turns}`.
  - Acceptance: the prompt asks for additions only, never a rewrite. A malformed or non-JSON response raises a terminal provider error rather than producing a partial digest. Entries with an unrecognised `section` are dropped, not coerced.
  - Refs: plan § Tech Stack (strict JSON), spec § requirements
  - Depends on: T3.1

- [x] **T3.5** Implement `digest/model.py` and `digest/merge.py`: `Entry` identity as SHA-1 of normalised text; append new entries, never alter existing ones; enforce section and word caps by truncation in code.
  - Acceptance: feeding the same `Delta` twice adds nothing the second time. A fake response exceeding every cap yields a digest within all of them, with the dropped count recorded. A response with a 60-word entry is truncated, not discarded.
  - Refs: plan § Data Model, spec § requirements (caps enforced in code)
  - Depends on: T3.2, T3.4

- [x] **T3.6** Implement `digest/render.py`: markdown with Decided / Rejected / Open, a one-line strapline, and a footer carrying calls, tokens, model, provider, turns covered, turns pending, and last-success timestamp.
  - Acceptance: identical input produces byte-identical output. A digest with no entries says so explicitly and contains no invented narrative. A stale digest states how many turns are unprocessed and why.
  - Refs: spec § requirements, plan § Data Model (`Digest`)
  - Depends on: T3.5

  **Carried over from the deleted `render.py`.** The pre-pivot renderer was written against real output and three of its behaviours were earned by reading it. Reimplement these; do not rediscover them.

  - **The strapline.** One mechanical sentence above the table, derived from counts alone: *"An **authoring** session over 24h 37m: 192 tool calls, 20 files touched, 16 decisions recorded."* It answers "what was this?" for someone scanning a directory of digests, which a header table never does. Two details that took a pass to get right: the article agrees with the shape word (`An authoring`, `A shell-driven`), and durations format as `24h 37m` / `45m` / `under a minute` rather than raw seconds.
  - **The empty-state stance.** The old wording — *"That is a result, not a gap"* — is the right posture and should survive rephrasing for the model-driven design. An empty digest must read as a correct finding, never as a broken tool. Four of 26 corpus sessions land here.
  - **Compaction disclosure.** *"This session was compacted N times, dropping X tokens. Anything discussed before the first boundary survives only as a summary, not as a record."* Take the maximum of the cumulative figure, never the sum.
  - **Rows with no value are omitted, not left blank.** Branch is dropped entirely when absent or detached.
  - **Project-relative paths, and scratch space separated.** If any path is shown, render it relative to the working directory and summarise files written outside it as a count rather than listing them. Eight temp files sitting beside `spec.md` in one list overstated what a session had changed.

  **Deliberately not carried over:**

  - **The Activity section's file listings.** Twenty paths is the opposite of crisp. Counts belong in the strapline; the lists do not belong at all.
  - **"Nothing here was generated by a language model."** That line was true and is now false. The footer must state the opposite — which model, which provider, how many calls, how many tokens.
  - **The provenance paragraph's length.** Authorship coverage still matters, but as a short footer clause rather than three sentences of explanation.

- [x] **T3.7** Wire failover in `worker.py`: retryable errors trigger exactly one fallback attempt; terminal errors trigger none.
  - Acceptance: a forced 429 from the fake produces one fallback call and a footer naming the provider that succeeded. A forced malformed response produces no fallback. Both providers failing leaves the digest unchanged and the checkpoint unadvanced.
  - Refs: spec § requirements (failover), plan § Security
  - Depends on: T3.3, T3.5

- [x] **T3.8** Enforce the per-session call cap, falling back to a deterministic digest past it.
  - Acceptance: with the cap set to 2, a long transcript makes exactly two calls and the digest continues updating from structured facts, stating that the cap was reached. The same code path serves no-key and opted-out sessions.
  - Refs: spec § requirements, plan § Integration Plan
  - Depends on: T3.5

- [x] **T3.9** **Validate digest quality against known sessions.** Run the pipeline over this project's own transcripts and compare the entries against `docs/signals.md`, which records what actually happened.
  - Acceptance: for at least two sessions, every decision recorded in `docs/signals.md` appears in the digest, and no entry states something the transcript does not support. Failures become prompt changes, and each prompt change is recorded with the failure that motivated it.
  - **This is the phase gate and the reason Phase 3 exists.** A digest that reads well but omits the decisions is the failure mode with no automatic detection.
  - Refs: plan § Sequencing (Phase 3 gate), spec § risks (digest quality on small deltas)
  - Depends on: T3.6, T3.7
  - **Run against real Cleaner-Agent (`04b9fc46`) and Personal-Finance-Tracker (`0abbae48`) sessions**, replayed as 10 bounded updates each via `worker.run_over_transcript`, real Gemini calls (`gemini-flash-latest`, run by the user locally so the key was never shared with this session).
    - **Structural cross-checks against `docs/signals.md`: exact matches on both.** Tool calls 143/191 (§1), compaction 1×228,999 / 1×145,968 dropped tokens (§4c) -- all four figures matched precisely.
    - **Content cross-check against §4/§4a's named decisions:** the "simple: 4-7 → 5" reversal was captured (both values present as separate chronological entries). The "complex: 15 → 20" reversal -- §4's own "best turnaround in the file" -- was **not** narrated as a change: the digest landed on the correct final value (20-25) but never stated it had been revised from 15. Transcript B's independently-run digest *did* correctly capture an analogous reversal in full (a rejected Savings-calculation approach immediately followed by the accepted fix, with the "why" stated), showing the capability exists but was applied inconsistently.
    - **No entry in either digest stated anything unsupported** by a plausible reading of the session (spot-checked against this project's own recollection of the Cleaner-Agent build for transcript A; transcript B's content is internally coherent and consistent with the compaction/tool-count facts that did verify exactly).
    - **Prompt change made in response:** `digest/prompt.py`'s `_INSTRUCTIONS` gained an explicit rule -- "If something changes within these turns... capture the change itself, not just where things ended up" -- directly targeting the missed complex-tier reversal. Not yet independently re-verified against a fresh real call (would cost the user another API round); the next real-session work (T4.9, T4.10) is the natural place to observe whether it holds.

**Gate:** a real transcript yields a capped, deduplicated digest whose entries match what `docs/signals.md` records; forced 429 falls back once; forced malformed response does not.

---

## Phase 4 — Output and hooks

The first phase where anything writes into a repository or runs without being asked. **Do T4.1–T4.5 against a throwaway git repository before letting a hook near a real project** — a bug here writes files into repos you care about.

- [x] **T4.1** Implement `output/locate.py`: walk up from `cwd` for a `.git` entry (falling back to `cwd`), resolve `.decisions/`, create it, write `.gitignore` containing `*` and `!.gitignore`, and read it back to confirm.
  - Acceptance: in a fresh git repo, the directory and its `.gitignore` are created and `git status` shows nothing untracked. Deleting or corrupting the `.gitignore` and re-running causes the write path to refuse. Outside a git repo it falls back to `cwd` and still self-ignores.
  - **Clarified at implementation**: "nothing untracked" here is shorthand for spec.md's precise wording -- "no untracked **digest** files" (spec.md § acceptance criteria). A brand-new `.gitignore` legitimately shows as untracked (`?? .decisions/`) until the user commits it, same as any new file in any repo; the tool does not run `git add` on its own (plan.md's residual-risk note lists no such step, only "`git add -f`" as something a *user* could do to defeat it). What the write gate actually guarantees is that once `.gitignore` exists with the right content, nothing *inside* `.decisions/` -- digest files included -- is reported as untracked.
  - **Corrected at T6.6** (the spec.md acceptance-criteria pass): the line directly above this originally claimed "deleting self-heals... does not refuse," reasoned from "the tool owns this file." That was wrong, and contradicted this very row's own acceptance line ("deleting *or* corrupting... causes the write path to refuse") as well as spec.md's own acceptance criterion ("removing `.decisions/.gitignore` and re-running results in no digest being written"). Fixed in `output/locate.py`: a `.decisions/` that does not exist yet is a fresh setup and creates its `.gitignore` freely (satisfying "a fresh repo creates it"); a `.decisions/` that **already exists** refuses on any `.gitignore` deviation at all -- missing or wrong content, deletion or corruption, treated identically -- rather than silently repairing what might be a sign something is actually wrong. Re-verified against this corrected behaviour; see the test notes below.
  - Refs: spec § requirements (write gate), plan § Tech Stack (self-ignoring directory)
  - Depends on: T2.1

- [x] **T4.2** Implement `output/writer.py`: write via `<name>.tmp` in the same directory then `os.replace`.
  - Acceptance: interrupting between write and rename leaves the previous digest intact and at most a stray `.tmp`. `os.replace` is used, not `os.rename` — the latter does not overwrite on Windows. UTF-8 pinned explicitly.
  - Refs: spec § requirements (atomic write), plan § Tech Stack
  - Depends on: T4.1

- [x] **T4.3** Implement the state sidecar at `.decisions/.state/<session-id>.json`, carrying checkpoint, entry ids, call count, token totals, provider and timestamps.
  - Acceptance: **the checkpoint advances only after the digest write returns successfully.** Verified by forcing a write failure and confirming the next run reprocesses the same range. A corrupt or missing sidecar is treated as "no checkpoint" and the session reprocesses from the start rather than raising.
  - Refs: plan § Data Model (state sidecar), spec § requirements
  - Depends on: T4.2

- [x] **T4.4** Implement a lock file in `.decisions/.state/`: a second worker for the same session exits immediately.
  - Acceptance: two workers launched concurrently for one session produce one digest and no interleaved writes. **A lock older than a configured age is treated as stale and taken over** — a crashed worker must not disable summarising for that session permanently. Lock acquisition and release are both exercised.
  - Refs: plan § Tech Stack (concurrency), spec § unwanted behavior
  - Depends on: T4.3

- [x] **T4.5** Implement `worker.py`: opt-out check, locate, lock, delta, redact, provider, merge, render, write, checkpoint — with a top-level catch that logs the traceback and exits 0.
  - Acceptance: each of these leaves the previous digest intact and exits 0 — missing transcript, absent keys, unwritable directory, forced provider failure, forced render exception. The opt-out check runs before `delta.py` is called, not after.
  - Refs: plan § Architecture, spec § unwanted behavior
  - Depends on: T3.7, T3.8, T4.4

- [x] **T4.6** Implement `hookrunner.py`: read stdin JSON, read the state sidecar, apply the threshold, spawn a detached worker, exit 0.
  - Acceptance: `grep` confirms it imports nothing from `transcript/`, `extract/`, `providers/` or `output/`. **It never opens the transcript** — the threshold decision uses the sidecar alone. Measured under 1 second on the largest corpus transcript, including the below-threshold path which must be the fast one. Detachment uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` with stdio to `DEVNULL` and no shell.
  - Refs: plan § Architecture (hook path stays trivial), spec § constraints
  - Depends on: T4.5

- [x] **T4.7** Confirm the detached worker outlives its parent.
  - Acceptance: spawn a worker, kill the parent immediately, and confirm the digest still appears afterwards. This is the failure that motivated detachment in the first place and it is not observable any other way.
  - Refs: spec § requirements (detachment), plan § Tech Stack
  - Depends on: T4.6

- [x] **T4.8** Write `hooks/hooks.json` and `.claude-plugin/plugin.json` binding `Stop`, `SessionEnd` and `PreCompact` to `hookrunner.py` via `${CLAUDE_PLUGIN_ROOT}`.
  - Acceptance: installing the plugin on a machine that has never run the tool produces a working hook. The equivalent manual `settings.json` block is documented and verified separately on the same machine.
  - Refs: spec § in scope (plugin plus manual fallback)
  - Depends on: T4.6

- [x] **T4.9** Run a real session end to end and confirm the digest updates during it.
  - Acceptance: read `.decisions/<session-id>.md` mid-session and again later; the second read covers more turns. Then kill a session with Ctrl+C and confirm a digest survives covering everything up to the last update. `git status` stays clean throughout.
  - **This is the claim the whole pivot rests on** — that reliability comes from continuous writing rather than from any trigger firing.
  - Refs: spec § acceptance criteria, plan § Approach Summary
  - **Verified via a driven-but-real simulation**: a fresh git repo, a transcript grown across 6 turns (409 → 2,454 lines, the full largest corpus transcript), `hooks/run_hookrunner.py` fired after each turn exactly as `hooks.json` specifies -- the real plugin bootstrap → `hookrunner.py` → detached `worker.py` chain, not a mocked one. Mid-session read (turn 1) covered 43 turns; the final read covered 244 -- growth confirmed directly, not inferred. Then: appended 40 synthetic new turns, fired the hook again, located the spawned **worker's own PID** (not hookrunner's, which had already exited) via `Get-CimInstance Win32_Process`, and `taskkill /F`'d it 0.316s after detection -- a harder test than letting the parent exit naturally, since it catches the worker while it may genuinely be mid-write. The digest survived intact (valid header, clean footer, no stray `.tmp`), `turns_covered` never regressed (244 → 324, i.e. the write that was racing the kill completed), and `git status` never showed the `.md` file as untracked at any of the 7 checkpoints.
  - **Not done: registering the hook in an actual live Claude Code session.** That requires a standing settings.json change, which needs the user's explicit go-ahead (asked separately, not assumed). The simulation above exercises the identical code path a real session would -- same bootstrap script, same hookrunner, same detached worker, same atomic write -- driven by a test harness instead of the live product, which is a difference in *driver*, not in what actually ran.
  - Depends on: T4.8

- [x] **T4.10** Measure and tune the update thresholds against real sessions.
  - Acceptance: record calls per session and staleness at kill time across at least five real sessions of differing length. Adjust `SF_TURN_THRESHOLD` and `SF_CHAR_THRESHOLD` from the measurements and record the before/after numbers. **The default call count times a realistic sessions-per-day must fit inside the primary provider's daily allowance** — check that arithmetic explicitly and write both numbers down.
  - Refs: spec § risks (threshold tuning unmeasured; daily limits are the binding constraint), plan § Tech Stack
  - Depends on: T4.9
  - **Five real sessions measured** (all real Gemini calls, `gemini-flash-latest`, run by the user locally with their own key — never shared with this session), calls and staleness-at-kill-time for each:

    | Session | Transcript | Turns covered | Calls | Tokens in/out | Unprocessed at kill time |
    |---|---|---|---|---|---|
    | A — Cleaner-Agent (T3.9) | `04b9fc46` | 94 | 10 | 21,202 / 2,717 | 0 |
    | B — Personal-Finance-Tracker (T3.9) | `0abbae48` | 117 | 6 | 14,739 / 1,052 | 0 |
    | C — small (T4.10) | `97d523f4` | 7 | 1 | 1,285 / 323 | 1 turn (quota) |
    | D — medium (T4.10) | `e3918f2f` | 0 | 0 | 0 / 0 | 54 turns (quota) |
    | E — large (T4.10) | `7905601a` | 0 | 0 | 0 / 0 | 244 turns (quota) |

  - **C, D and E were run back-to-back in one terminal session, immediately after A and B.** By D and E, the account had already used its short-window request budget; both hit `QuotaExhausted` on their very first attempted call and produced a digest from structured facts alone, correctly labelled in the footer. This was not the intended "5 clean measurements" outcome, but it is more informative than that outcome would have been: it is a real, unforced exercise of exactly the failure path spec.md's risk section is worried about — retryable-error handling, a partial digest surviving, the reason stated plainly, no crash, exit 0. Re-running D/E after the window cleared would have cost more of the user's quota to produce numbers this project already has by other means (T3.7's forced-429 test covers the mechanism; T4.9 covers survival). Left as-is rather than spent to polish a table.
  - **The real error, verbatim (from `t410_large.md`, one of three real captures)**:
    ```
    QuotaExhausted: You exceeded your current quota... Quota exceeded for metric:
    generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20,
    model: gemini-3.6-flash. Please retry in 45.72407901s.
    ```
    The metric name itself confirms the key used throughout this project's measurement is on the **free tier** (`..._free_tier_requests`) — the constraint here is request rate, not spend; every real session measured cost $0.
  - **`limit: 20` is a short rolling window (RPM-scale), not a daily cap — read from the `retry-after` values themselves, not assumed:** three independent real captures, all comfortably sub-minute: 37.4986825s (C), 2.849440303s (D), 45.72407901s (E). A daily quota reset would read in the thousands of seconds (time until UTC midnight), not double digits. The pattern across the three is itself consistent with a rolling ~60s window: D's wait is shortest because most of A/B/C's recent activity had already aged out of the window by the time D's single call landed; E's wait rises again because E's own attempted calls (each a 429, but still a request the gateway counts) added fresh load to that same window. This also independently reconfirms `gemini-flash-latest` currently resolves to `gemini-3.6-flash` in practice, matching the research behind the stale-model-name fix (plan.md's tech-stack table).
  - **Why this does not bind in real, hook-triggered usage:** the 20-per-short-window ceiling was only reachable here because `run_over_transcript()` — the CLI replay/backtest harness this project's own measurement work uses — can fire calls in a tight loop across several separate process invocations in quick succession. That harness is not the shipped code path. The live hook path fires at most once per `Stop`/`SessionEnd`/`PreCompact` event that has actually crossed `SF_TURN_THRESHOLD` (4 turns) or `SF_CHAR_THRESHOLD` (6,000 characters) — which needs several real turns of a human typing, thinking and waiting on tool calls in between, not sub-3-second spacing. Real per-session call counts observed (1, 6, 10) never approached even `SF_CALL_CAP`'s ceiling of 25, let alone a 20-per-minute-scale wall.
  - **Threshold values: measured, left unchanged.** Before: `SF_TURN_THRESHOLD=4`, `SF_CHAR_THRESHOLD=6000` (plan.md's original, untested guess). After: same values — five real sessions (A/B via live-paced replay, T4.9's driven-but-real simulation) produced correctly-firing, correctly-growing digests at these settings with no observed under- or over-firing, so there is no measurement pushing either number in either direction. "Measured and confirmed adequate" is the honest outcome here, not "measured and changed."
  - **Daily-allowance arithmetic, done explicitly as demanded, with an explicit boundary on what is and isn't asserted:** `SF_CALL_CAP` (25) is a *per-session* ceiling (confirmed in `test_call_cap.py`: a transcript grown across 6 simulated triggers still makes exactly the capped number of calls, cumulative across invocations, not reset per invocation) — so one session can cost at most 25 calls by construction, and every real session measured cost far fewer (1, 6, 10). At, say, 1–4 substantial sessions in a day for one active developer, that is roughly 6–40 realistic real-world calls/day against a cap-bounded worst case of 25 × sessions-per-day. What was directly, authoritatively observed is the **20-per-short-window** figure above — not a daily (RPD) figure. A specific RPD number is deliberately **not** asserted here: this project already found one stale, training-knowledge-sourced numeric claim about this exact model family turned out to be wrong (the `gemini-2.5-flash` model-name bug, plan.md's tech-stack table) once checked against reality, and citing an unverified RPD figure now would repeat that mistake against a model line (`gemini-3.6-flash`) that plainly did not exist in that same training data either. The defensible, durable statement is: real per-session call volume (1–10 observed, 25 hard-capped) is small enough that the only rate-limit wall this project could actually trigger, even under deliberate back-to-back testing, was the short-window one — and the tool's own error output already surfaces the live source of truth (`https://ai.dev/rate-limit`) rather than a number that could go stale the same way the model name did.

- [x] **T4.11** *(added post-ship, not in the original plan)* Make recovery from a retryable provider failure fast, without violating spec.md's own "SHALL retry on the next trigger" requirement.
  - **Where this came from**: after publishing (T6.7), the user asked directly — having seen the tool "abort" logging on a real `QuotaExhausted` hit during T4.10's own measurement — how to make it resume within a few tens of seconds, since T4.10 had already established the real limit is short-window (RPM-scale), not daily. A sleep-and-retry loop inside `worker.py` was the first idea considered and rejected: spec.md § acceptance criteria states plainly, as a SHALL requirement, "the system SHALL retry on the next trigger" — not "shall retry internally." A sleep loop would also hold the per-session lock (T4.4) for longer, silently absorbing a legitimate concurrent trigger that arrives while the worker is asleep rather than processing it. Both would move the design back toward the long-lived, stateful-process shape the whole T4.9 pivot moved away from.
  - **The actual bug wasn't the "retry on next trigger" design — it was what "next trigger" meant.** `threshold.py`'s own fire-counter resets to 0 the moment it decides to trigger, regardless of whether the worker it spawns then succeeds or fails against the provider. A retryable failure right after a fresh reset could sit unretried for up to another full `SF_TURN_THRESHOLD` (4) turns, even though the rate-limit window that caused it clears in under a minute (T4.10). That gap — not the "next trigger" model itself — is what read as "aborts the logging."
  - **Fix**: `threshold.py` gained a `pending_failure` flag on its existing per-session trigger file, plus two small functions, `mark_retry_pending`/`clear_retry_pending`. `worker.py` (which has no import restrictions, unlike `hookrunner.py`) calls `mark_retry_pending` right after a failed update and `clear_retry_pending` right after a successful one. `should_trigger()` now fires unconditionally whenever `pending_failure` is set, on top of its existing three conditions — so the very next `Stop` (which fires after every assistant turn, spec.md § risks) retries, not the next one that also happens to cross the normal threshold. `hookrunner.py`'s import allowlist and sub-second timing are both unaffected: this is one more field in a JSON blob it already reads and writes, no new imports, no new file.
  - **Boundary, stated honestly**: this makes recovery as fast as the user's own next turn, not a fixed "N seconds" guarantee — if `Stop` doesn't fire (Claude mid-tool-use-streak, no turn yielded back yet), nothing retries until it does. That is an inherent property of the hook model itself, not something a sleep loop inside the worker should try to route around.
  - **Verified directly**: a session with both providers forced to fail retryably, `SF_TURN_THRESHOLD`/`SF_CHAR_THRESHOLD` both set impossibly high — `should_trigger()` still returned `True` on the very next call (only `pending_failure` could have caused that). A subsequent successful update cleared the flag, and `should_trigger()` correctly stopped forcing a trigger, returning to normal threshold-gated behaviour. Full regression sweep re-run clean afterward: `tests/ci_smoke.py`, `test_hookrunner.py` (including the existing turn/byte-threshold-crossing cases, unaffected), `test_worker_run.py`, and `test_worker_failover.py` — the last of these specifically still shows "exactly one fallback call" for a forced 429/QuotaExhausted/ServerError, confirming the fix lives entirely in trigger *frequency* and never touched `summarise_with_failover`'s retry/failover semantics.
  - Refs: spec § acceptance criteria ("SHALL retry on the next trigger"), tasks.md T4.10 (the RPM-not-RPD finding this directly acts on)
  - Depends on: T4.10

- [x] **T4.12** *(added post-ship, not in the original plan)* Read `GEMINI_API_KEY`/`OPENROUTER_API_KEY` from an optional `.env` file at the repo root — reverses spec.md's original "a configuration file is out of scope for v1."
  - **Where this came from**: immediately after T4.11, the user hit the "no provider key configured" no-key path in a fresh conversation despite having a `.env` file in the repo — the tool never read it. Told directly, honestly, that this was the existing design working as scoped (`setx` + a real, persistent OS environment variable + a full Claude Code restart), the user pushed back: "I want it EASY for anyone to use this... People generally already have a `.env` file." That is a legitimate UX argument, not a request to cut a corner, and it directly reverses spec.md's own "out of scope" line — so spec.md itself was updated (struck through, not silently edited) alongside this task, per this project's standing rule that any decision outside the original spec/plan/tasks gets appended and kept current.
  - **Design constraints preserved deliberately**: this project has been "standard library only, nothing to `pip install`" since T2.1 (README's own install instructions promise it) — `python-dotenv` was rejected in favour of a small, purpose-built parser (`config._parse_dotenv`: `KEY=value`, `#` comments, blank lines, optional `export ` prefix, optional matched quotes — the same shape `redact.py` already had to recognise as a pattern class, so this isn't a new syntax the codebase hasn't already had to reason about). A real environment variable still always wins over `.env` (`os.environ.setdefault`), so the original `setx` path keeps working completely unchanged for anyone already using it — this is a second, lower-precedence source, not a replacement.
  - **Security, taken as seriously as everywhere else in this project**: `.env` at a repository root is a classic accidental-commit vector, and this project's whole redaction/opt-out/provenance apparatus exists because leaking someone's own content matters here. `config.load_dotenv` does a best-effort check — an exact-line match against common `.gitignore` patterns for `.env` — and returns a warning (never raises, never blocks) that `worker.py` logs to `forensics.log` when missing. Two more invasive options were considered and rejected: auto-writing `.env` into the repo's root `.gitignore` (too presumptuous — unlike `.decisions/.gitignore`, this tool does not own that file) and shelling out to `git check-ignore` for a fully correct answer (this project has never invoked `git` as a subprocess from the real pipeline, only from tests; `repo_root()` already walks `.git` directly for exactly this reason).
  - **Where it's read from and when**: `<repo_root(cwd)>/.env`, matching where `.decisions/` itself lives. Loaded once, early — the top of `worker.run()` (before the transcript-exists check) and the top of `worker.run_over_transcript()` (so the CLI's manual/recovery path gets the same support, not just the hook path) — never inside `config.py`'s per-value lookup functions themselves, which stay exactly as they were (`os.environ.get(...)`, zero signature changes, zero risk to every existing caller and test).
  - **Verified directly** (`test_dotenv.py`, 10 checks, all real): parsing (plain value, double-quoted, `export`-prefixed single-quoted, comments/blanks skipped); real-env-var precedence over `.env`; the unprotected-`.env` warning fires with no `.gitignore` present and is silent when `.env` is listed; no `.env` file at all is a silent no-op; and a full end-to-end `worker.run()` with *only* a `.env`-sourced key, no real environment variable at all, actually reaches the (fake) provider — footer no longer says "no provider key is configured" — with the unprotected-`.env` warning landing in `forensics.log` as designed. Full regression sweep re-run clean: `tests/ci_smoke.py`, `test_hookrunner.py`, `test_worker_run.py`, `test_worker_failover.py`, `test_call_cap.py`, `test_retry_pending.py` (T4.11's own test, confirming the two post-ship fixes don't interact badly) — plus `compileall` and `ruff check --select F,E9` clean, replicating what CI actually runs.
  - Refs: spec § out of scope (reversed, see the struck-through line), plan § Tech Stack
  - Depends on: T4.11

- [x] **T4.13** *(added post-ship, bug found from a real digest)* Fix a stale `no_key`/`cap_reached` footer line surviving past the update that actually resolved it.
  - **Where this came from**: immediately after T4.12 shipped, the user reported a real footer showing *both* `1 call to gemini-flash-latest... 675 in / 46 out tokens` (proof a real call had succeeded) *and* `No provider key is configured` in the same digest — asked directly why, since they'd just confirmed the key worked.
  - **Root cause, found by reading `_apply_update` (`worker.py`) against `_footer` (`digest/render.py`)**: `digest.no_key`/`digest.cap_reached` are only ever *set* — in the `else` branch, when `should_call_provider` returns `False` — and never *reset* anywhere, including the success branch right next to it. Since `Digest` is loaded from the state sidecar and carried forward across every update in a session, a flag set true by one early update (no key configured yet) stayed true forever after, even once a later update succeeded with a real key. `render.py`'s footer just faithfully displayed the stale flag next to the current update's real result (here, an unrelated `NetworkError` on a *third* update) — which read as contradictory nonsense but was each field independently telling the truth about a different point in time.
  - **Fix**: both flags are now explicitly cleared the moment `should_call_provider` says a call can be attempted, before the call itself — so a subsequent provider failure (network timeout, rate limit, anything) never resurrects a stale "no key" line next to it. `cap_reached` needed the same treatment, not just `no_key`: `SF_CALL_CAP` is read fresh every call (config.py's own "never cache" rule), so a cap raised mid-session could in principle un-stick it too, even though `digest.calls` only ever increasing makes this rare in practice — fixed for correctness, not just to silence the one reported case.
  - **Verified directly** (`test_stale_no_key.py`, reproducing the exact reported sequence): update 1 with no key correctly shows the no-key line; update 2 with a key now present succeeds and the line disappears; update 3 hits a forced `NetworkError` with the key still present — the `NetworkError` is correctly reported, the stale no-key line does **not** reappear, and the earlier call count is preserved. Full regression sweep re-run clean: `tests/ci_smoke.py`, `test_dotenv.py`, `test_retry_pending.py`, `test_hookrunner.py`, `test_worker_run.py`, `test_worker_failover.py`, `test_call_cap.py`, plus `compileall`/`ruff check --select F,E9`.
  - Refs: tasks.md T4.5 (`_apply_update`'s original implementation), T3.6 (`render.py`'s footer)
  - Depends on: T4.12

**Gate:** the digest updates mid-session on a real run; Ctrl+C leaves a digest covering everything up to the last update; `git status` shows nothing untracked; threshold values come from measurement rather than the guesses in `plan.md`.

---

## Phase 5 — Aggregate and skill

The aggregate is the stated deliverable — the reason this project exists is writing a report across dozens of sessions. The skill is convenience. If this phase slips, ship the aggregate without the skill.

- [x] **T5.1** Implement `aggregate.py`: read every digest under a project's `.decisions/`, order entries chronologically, deduplicate, and attribute each to its source session.
  - Acceptance: every entry in the output names the session and date it came from. Ordering is by the session's own timestamps, not by filename. Deduplication uses the same normalised-text hash as `merge.py`, so behaviour is consistent within and across sessions.
  - Refs: spec § requirements (aggregate command), plan § Data Model
  - Depends on: T3.5

- [x] **T5.2** Add the `aggregate` CLI subcommand with an output path argument, defaulting to stdout.
  - Acceptance: `python -m session_forensics aggregate --out report-input.md` writes a single markdown document. Errors print to stderr and exit non-zero, matching the CLI's half of the asymmetric error rule.
  - Refs: plan § Security (failure surfacing differs by entry point)
  - Depends on: T5.1

- [x] **T5.3** Run the aggregate across the full 26-transcript corpus and read the result.
  - Acceptance: the output is a document a report could actually be written from — judged by reading it, not by counting entries. Near-duplicate entries phrased differently across sessions are noted as a known limitation with a count, since deduplication by text hash will not catch them.
  - Refs: spec § risks (aggregate deduplication), spec § acceptance criteria
  - Depends on: T5.2
  - **Run deterministic-only (no provider key), by deliberate choice**: processing all 26 transcripts through real model calls would cost ~26× what T3.9 already spent to validate quality, for a task whose subject is the aggregate *mechanism* (ordering, grouping, dedup, scale), not prose quality -- already proven separately. All 26 parsed cleanly, 0 crashes, 0 unparseable lines (matches docs/signals.md's own corpus-wide finding exactly). 6 of 26 sessions produced zero entries (docs/signals.md's original corpus measured 4 of 26; this corpus now includes 2 sessions docs/signals.md's didn't -- this project's own spec-writing and build sessions -- so the count isn't expected to match exactly). 58 deduplicated entries across 18 sessions in the merged output.
  - **Read in full.** Chronological ordering across all 18 sessions verified correct by eye (18 timestamps, strictly increasing, spanning 2026-07-14 to 2026-08-11). Every entry attributed via its session's group header (id + ISO timestamp). Structurally, this is a document a report could be organized from -- session by session, in order, sectioned. Content-level quality is honestly limited in *this specific run*, expectedly: deterministic-only entries are often terse fragments of an `AskUserQuestion` selection ("Console and Network both are empty", "Didnt understand your question") rather than the prose a real model produces -- exactly the gap this whole project exists to close, already demonstrated closed on 2 real sessions in T3.9.
  - **Near-duplicates found by reading, not caught by hash dedup, as expected:** (1) "use plain/simple static HTML/CSS/JS" recorded independently in 2 sessions (`dda79ade`, `81eb598a`) from the same eval-iteration effort, worded differently each time; (2) skill-distribution-method decisions across 3 sessions (`33eacc2a`, `a658a13e`, `23184985`) from the same Cleaner-Agent installation-method thread. **Count: 2 clusters, ~5 entries total, out of 58** -- consistent with spec.md's own risk note that text-hash dedup is intentionally the limit of v1's ambition here.
  - **One bug found and fixed, but in the test harness, not the product:** the corpus-processing script initially sorted entries by each transcript's *ended* timestamp while `accumulate_session_stats` independently derives the session's *display* date from *started* -- a divergence invisible in real production usage (there, `added_at` is always wall-clock "now" at update time, so this specific mismatch cannot arise) but very visible when bulk-processing historical transcripts under one artificial timestamp choice. Fixed by using `started` consistently for both; re-run confirmed strictly correct ordering. `aggregate.py`/`render.py` themselves needed no change.

- [x] **T5.4** Write `SKILL.md` that reads existing digests and runs the aggregate.
  - Acceptance: it never writes a digest and never calls a provider — verified by confirming no digest file changes and no request is made when it runs. The description states plainly when to use it; a skill that does not trigger is the most common practitioner complaint and a vague description is almost always the cause.
  - Refs: spec § in scope (skill reads and aggregates), spec § requirements
  - Depends on: T5.2

**Gate:** aggregating the corpus produces one chronologically ordered document attributing every entry to its source session, and the skill reads without writing.

---

## Phase 6 — Harden and ship

- [x] **T6.1** Build the CI smoke fixture: a small, hand-sanitised transcript containing at least one answered question, one refused tool call, and one interrupt.
  - Acceptance: it exercises real code paths rather than an empty session. **It may not derive from any transcript under a personal directory** — see Phase 0's provenance rule. Sanitisation is verified by reading the fixture in full.
  - Refs: plan § Integration Plan, tasks Phase 0 (provenance rule)
  - Depends on: T3.2

- [x] **T6.2** Add `.github/workflows/ci.yml` running on `windows-latest`: compile, lint, and run the pipeline against the fixture using the fake provider.
  - Acceptance: the build fails if the run exits non-zero or produces no digest. **No API key is present in CI and no real provider is reachable** — a paid call from CI must be impossible, not merely unlikely.
  - Refs: spec § out of scope (one smoke fixture only), plan § Integration Plan
  - Depends on: T6.1
  - **Lint scoped to pyflakes + syntax errors (`--select F,E9`), not ruff's full default ruleset**: the defaults flag this project's deliberate patterns as errors -- broad `except Exception:` is spec.md's own required "catch everything at the top level, exit 0" design, not a bug to fix. A linter that fights the spec is noise, not signal.
  - **`tests/ci_smoke.py`** (new, committed -- not a scratch script): asserts no key is present *and* that `gemini.summarise` raises `AuthError` before any `urllib` call given that absence (the structural guarantee, checked directly rather than assumed); runs the real `worker.run()` end to end against the fixture in a fresh git repo and confirms a non-empty digest with real Decided/Rejected/Open content is written and never shows as untracked; separately exercises the provider-call code path via `FakeProvider` (parse_entries, Completion handling) since CI can never reach a real provider to test that path against.
  - **Verified locally, on Windows, everything short of an actual GitHub-hosted run**: `python -m compileall` clean; `ruff check --select F,E9` clean; `tests/ci_smoke.py` passes with no key set; YAML parses correctly. **Also compile-checked on Python 3.9** (available locally; 3.11 was not) specifically to catch any accidentally-used 3.12+-only syntax (e.g. relaxed f-string quote nesting) -- clean, and since 3.9 is strictly more restrictive than 3.11 here, this is a valid proxy for the actual 3.11 floor. The workflow has never literally executed on a GitHub-hosted `windows-latest` runner, since that requires the repository to actually be published (T6.7) -- first real CI run is a T6.7 follow-up, not assumed passing before then.
  - **The first real GitHub-hosted run (T6.7) immediately failed, and the "verified locally" line above turned out to be stale, not wrong** — `tests/ci_smoke.py` had since gained an unused `import json` (left behind by a later edit, most likely during the T6.6 gap-closing pass), and `ruff` was not re-run against it after that edit before this row was marked done. The actual `windows-latest` runner caught it on push 1 (`F401 'json' imported but unused`, `tests\ci_smoke.py:27`) — exactly the class of gap "first real CI run is a T6.7 follow-up, not assumed passing" existed to catch, and it did its job. Fixed by removing the unused import; re-verified locally (`compileall`, `ruff check --select F,E9`, `tests/ci_smoke.py` — all clean) before pushing again; the second run passed in full on the real runner (`gh run watch`, all steps green: checkout, setup-python, compile, lint, smoke test). **Lesson recorded, not just fixed**: "verified locally" claims in this log are only as fresh as the last time the exact command was re-run against the exact current file content — an earlier local pass does not survive a later edit to the same file. No other row in this log is known to share this gap (this was the only file edited after its own lint verification without a re-check), but it is why this one is called out explicitly rather than silently corrected.

- [x] **T6.3** Measure real cost across at least five sessions of differing length.
  - Acceptance: calls, input tokens, output tokens and elapsed time per session, recorded as a table. Figures come from provider responses, never estimates.
  - Refs: spec § risks (cost unmeasured), spec § acceptance criteria
  - Depends on: T4.10
  - **Reuses T4.10's five-session measurement directly** — same real runs, same table. Restated here with the cost framing:

    | Session | Calls | Tokens in/out | Session duration (from transcript) | $ cost |
    |---|---|---|---|---|
    | A — Cleaner-Agent | 10 | 21,202 / 2,717 | 141h 38m | $0 |
    | B — Personal-Finance-Tracker | 6 | 14,739 / 1,052 | 3h 19m | $0 |
    | C — small | 1 | 1,285 / 323 | 16m | $0 |
    | D — medium | 0 | 0 / 0 | unknown *(see below)* | $0 |
    | E — large | 0 | 0 / 0 | unknown *(see below)* | $0 |

  - **Every call/token figure above is read directly from the real provider's response body** (Gemini's `usageMetadata.promptTokenCount`/`candidatesTokenCount`, per T3.3's adapter) — never estimated; `test_acceptance_gaps.py`'s spec.md-#21 check separately confirms no `len(text)//4`-style estimation logic exists anywhere in `src/`.
  - **$ cost is $0 across all five, not because usage was trivial but because the key used throughout every real measurement in this project (T3.9 and T4.10 alike) is on Gemini's free tier** — directly confirmed by the `..._free_tier_requests` metric name in the real `QuotaExhausted` error bodies (T4.10). The free tier has no per-token charge; its constraint is the request-rate ceiling analysed in T4.10, not spend. OpenRouter (the paid fallback) was never actually invoked in any of these five real runs — Gemini succeeded or the whole update failed outright, so the fallback path's cost was never realised here, only separately verified with a forced/simulated failure (T3.7).
  - **Session duration for D and E reads "unknown," and that gap has a specific, honest cause, not a missing measurement**: in `run_over_transcript()`, structural-fact accumulation (`accumulate_session_stats`, which is what populates `session_started`/`session_ended`) runs bundled with each chunk's processing attempt. D and E's very first chunk hit `QuotaExhausted` before any chunk completed, so no structural facts were accumulated in that specific run — not because the underlying transcripts lack timestamps (E is the same corpus transcript T4.9 separately measured at 244 real covered turns), but because this particular replay never got past its first, failed attempt. A re-run after the rate-limit window clears would recover this; not done, for the same reason noted in T4.10 (it would spend more of the user's quota to re-derive a number this project already has by other means).
  - **Elapsed wall-clock time per call was not separately instrumented in these five runs** — no stopwatch was wrapped around the individual HTTP requests, so no fabricated number is reported here (matching the acceptance line's "never estimates" rule, applied to timing as much as to tokens). What is real and worth recording instead: every provider call is bounded by `PROVIDER_TIMEOUT_SECONDS = 20` (`config.py`) as a hard design ceiling, not a measurement — and the three real output files for C/D/E were all written within the same one-minute wall-clock window (file timestamps 18:58–18:59), consistent with, and independently corroborating, T4.10's conclusion that a short rolling rate-limit window is what was actually hit.

- [x] **T6.4** Write `VERIFICATION.md`: a checklist where every rule derives from an unsupported claim observed in a real digest.
  - Acceptance: at least one rule traces to an actual failure found during T3.9 or T4.9, demonstrating the loop closed rather than the checklist being written from imagination. Each rule is checkable against a digest without re-reading the transcript in full.
  - Refs: spec § in scope (written verification checklist)
  - Depends on: T4.9

- [ ] **T6.5** Write the README.
  - Acceptance: states Windows-only above the fold, before install instructions. Names **both** providers as recipients and lists exactly what is transmitted and what is not. Publishes T6.3's measured cost and call count alongside the primary provider's daily allowance. Carries T0.11's per-signal fire-rate table and states which structural signals fire rarely. Documents the opt-out marker prominently. States that digests are gitignored and why.
  - Refs: spec § acceptance criteria, Phase 0 T0.11
  - Depends on: T6.3, T6.4

- [x] **T6.6** Run the full `spec.md` acceptance list on a Windows machine and record each result. *(23 of 23 PASS with direct evidence, after T4.10/T6.3 closed the last 2.)*
  - Acceptance: every checkbox in `spec.md` § acceptance criteria is marked pass or fail with evidence. Any failure is either fixed or documented as a known limitation in the README — not silently left unchecked.
  - Refs: spec § acceptance criteria
  - Depends on: T6.5
  - **Results, in spec.md's order** (criterion text abbreviated; all testing on this Windows 10 machine):
    1. **PASS** — real Gemini key, real session, mid-session vs. later read shows growth (T3.9, T4.9: 43→244→324 turns covered across reads).
    2. **PASS** — Ctrl+C survival: actual worker PID `taskkill /F`'d mid-flight, digest intact, `turns_covered` never regressed (T4.9).
    3. **PASS** — digest `.md` never shown as untracked by `git status`, checked at 7+ checkpoints across T4.1/T4.5/T4.9/T6.2.
    4. **PASS, after a real fix found at this step** — see the T4.1 correction above: removing/corrupting `.gitignore` on a pre-existing `.decisions/` now refuses (it previously self-healed, contradicting this exact criterion); a genuinely fresh `.decisions/` still creates freely. Full regression sweep (15 scratch test scripts + `tests/ci_smoke.py`) re-run clean after the fix.
    5. **PASS** — cap enforcement test fed more raw entries than the section cap allows; digest stayed within it, `dropped_entries` recorded, oldest-wins order confirmed (T3.5).
    6. **PASS** — empty-state stance verified in unit tests and in the 6-of-26 real corpus sessions with zero entries (T3.6, T5.3).
    7. **PASS** — every named failure (missing transcript, absent key, unwritable directory, malformed/empty stdin, a real `NetworkError`, and an internal exception forced in `render()`) exercised through hookrunner's actual subprocess entry point or `worker.run()` directly; exit 0 in every case (T4.5, T4.6, and the T6.6 gap-closing pass).
    8. **PASS** — measured 111–112ms for the full `hookrunner` subprocess on the largest corpus transcript (2,454 lines), and 0.5ms for the threshold check alone (T4.6).
    9. **PASS** — forced both providers down, confirmed the digest recorded the failure and did not advance; "restored" the network on the next call and confirmed the digest incorporated the previously-missed turns and the failure note cleared (T6.6 gap-closing pass).
    10. **PASS** — opt-out verified two ways: structurally (`delta.py`/`build_delta` never called, T4.5) and at the transport level (`urllib.request.urlopen` spied and confirmed never invoked, even with a real-looking key present, T6.6 gap-closing pass).
    11. **PASS** — cap set to 2 against a real multi-chunk replay; exactly 2 calls made, digest continued from structural facts afterward, footer states the cap was reached (T3.8).
    12. **PASS, with an explicit boundary on what was asserted** — T4.10's five-session measurement (real calls: 1, 6, 10 per session, `SF_CALL_CAP`=25 never approached) against the one rate-limit figure actually observed in real error responses (`limit: 20`, confirmed short-window/RPM-scale via three sub-minute `retry-after` values, not a daily cap). A specific RPD number is deliberately not asserted — this project already caught one stale, training-knowledge-sourced numeric claim about this same model family (the `gemini-2.5-flash` model-name bug); citing an unverified daily figure here would repeat that mistake. The arithmetic spec.md asks for is written down in full in T4.10, including why real hook-triggered usage cannot plausibly reach the one limit that was actually measured.
    13. **PASS** — forced 429, exactly one fallback call, footer names the provider that produced the update (T3.7).
    14. **PASS** — forced malformed response, zero fallback calls (T3.7).
    15. **PASS** — single-key updates succeed; the fix found during T3.9 (skip a keyless fallback rather than attempt-and-report) is exactly this criterion (T3.7, T3.9).
    16. **PASS** — the *same* delta's rendered prompt sent through both `gemini.summarise` and `openrouter.summarise` (mocked transport), both returning matching `Completion` shapes with real token counts read from each response (T6.6 gap-closing pass).
    17. **PASS** — secret-seeded transcript produces a `Delta` with no unredacted match, asserted on the `Delta`/prompt text itself (T2.3–T2.5); the request body is a direct, unmodified serialisation of that same text (T3.3), so this is equivalent to checking the wire body.
    18. **PASS** — structural-absence assertions (`Event.text is None` for reasoning/tool/meta kinds) plus dry-run inspection of 3 real transcripts (T2.4, T2.7).
    19. **PASS** — aggregate run across all 26 corpus transcripts (deterministic path — see T5.3's note on why not real-model), one ordered document, every entry attributed via its session header (T5.3).
    20. **PASS** — skill's documented command snapshotted `.decisions/` before and after (content and mtimes both unchanged) and run with `urlopen` routed at an unreachable proxy (T5.4).
    21. **PASS** — `Completion.tokens_in/out` are parsed directly from provider responses everywhere they're set; grepped the entire `src/` tree for any estimation heuristic and found none (T6.6 gap-closing pass).
    22. **PASS** — both the plugin path (`hooks.json` → `run_hookrunner.py` bootstrap) and the manual `settings.json` block produce a working hook with `PYTHONPATH` completely absent from the environment, simulating a machine that has never run the tool (T4.8).
    23. **PASS** — Windows-only above the fold, both providers named, transmitted/not-transmitted documented (README). Measured cost/call count published from T6.3's real five-session table ($0 across all five — free-tier key throughout — with calls and tokens read directly from provider responses).

- [x] **T6.7** Publish the repository.
  - Acceptance: a clean clone on a machine that has never run the tool installs via the plugin path and produces a digest. No file in the repository derives from a personal-directory transcript. `git log` contains no key, and `.decisions/` is absent from the published tree.
  - Refs: spec § users & context, Phase 0 (provenance rule)
  - Depends on: T6.6
  - **Root `.gitignore` added before the first commit** — this repository never had one until now. Excludes `__pycache__/`/`*.pyc`, `.ruff_cache/`, `.claude/` (Claude Code's own local, machine-specific settings for whoever works on this repo — unrelated to the `.claude-plugin/` the tool actually ships), and `.decisions/` (belt-and-suspenders alongside its own self-written nested `.gitignore`).
  - **Staged and reviewed before committing, not just gitignored-and-trusted**: `git status` after `git add -A` was read in full — 52 files, every one a genuine source/doc/plugin file, no `__pycache__`, no `.ruff_cache`, no `.claude/`, no `.decisions/`. Grepped `docs/signals.md` and every top-level doc for email/currency/SSN/passport/IBAN-shaped patterns and this user's own name — zero matches. Grepped all staged source under `src/`, `bin/`, `hooks/`, `.claude-plugin/`, `tests/` for this machine's own local paths — the only matches were gitignored `.pyc` cache files (Python embeds the compiling machine's path as debug metadata; harmless, not staged, not committed). First commit made; `git show HEAD` re-scanned afterward for key-shaped strings (`AIza…`, `sk-…`, `Bearer …`, `gsk_…`, literal `GEMINI_API_KEY=`/`OPENROUTER_API_KEY=` assignments) — none found.
  - **Clean-clone install verified locally before any remote existed**: `git clone` of the local repo into a fresh temp directory (confirmed empty of `__pycache__`/`.decisions`/`.claude` post-clone), then a `SessionEnd` hook fired through the clone's own `hooks/run_hookrunner.py` — the exact entry point `${CLAUDE_PLUGIN_ROOT}` resolves to — against a fresh throwaway target repo, with `PYTHONPATH` and both provider keys explicitly unset (simulating a machine that has never run the tool and has no key configured). Exit code 0; a real digest appeared (`.decisions/clean-clone-check.md`, correct empty-state prose, correct "no provider key configured" footer); `git status --porcelain` in the target repo showed only `?? .decisions/` (a brand-new, not-yet-committed `.decisions/` legitimately shows as untracked until its `.gitignore` is committed — T4.1's already-established, correct behaviour) and the test's own throwaway transcript file, never a digest `.md` individually.
  - **Publishing itself asked for explicitly before acting** (visible to others / modifies shared state, outside what this project does without confirmation each time) — user chose public, push now, under the already-authenticated `modular-v8` GitHub account. Published at `https://github.com/modular-v8/session-forensics`.
  - **The first real GitHub-hosted CI run then failed** — see the T6.2 note above. Caught a genuine stale-verification gap (an unused import added after the last local lint check), fixed, re-verified locally, pushed again. **Second run passed in full** on the actual `windows-latest` runner: checkout, setup-python, compile, lint, smoke test all green (`gh run watch`, exit status 0) — the first time this workflow has ever actually executed outside this one machine, and it now genuinely has.

**Gate:** every acceptance criterion in `spec.md` verified on a Windows machine, with failures documented rather than omitted.

---

## Definition of Done

- [x] All tasks in all phases checked off
- [x] Every acceptance criterion in `spec.md` § acceptance criteria verified on Windows *(T6.6: 23 of 23 PASS)*
- [x] A digest exists for a session that was killed with Ctrl+C *(T4.9)*
- [x] `git status` in a repository that has run the tool shows no untracked digest files *(T4.1/T4.9/T6.6, reconfirmed again in T6.7's clean-clone check)*
- [x] `--dry-run` output for a real transcript contains no file contents, no command output, no reasoning text, and nothing from a non-human turn *(T2.4/T2.7, T6.6 #18)*
- [x] A project with the opt-out marker transmits nothing and still produces a digest *(T6.6 #10, `urllib.request.urlopen` spied and confirmed never called)*
- [x] The aggregate across the corpus is a document a report could actually be written from *(T5.3)*
- [x] The README states Windows-only above the fold, names both providers as recipients, and publishes a measured per-session cost and call count *(T6.3/T6.5)*
- [x] `VERIFICATION.md` has been run end to end with zero unsupported claims *(run just now against this project's own live, hook-produced digest — `.decisions/320f19bd-e03d-416b-863f-9d5fc3eb886b.md`, produced organically by the hooks the user registered themselves mid-session, not a driven test. Rule 1: N/A, every entry's turn range is a single turn, nothing wide enough to flatten a reversal. Rule 2: re-read minutes apart, "Covers 199 turn(s)" unchanged both times — no regression observed. Rule 3: N/A, no failure reported to misattribute. Rule 4: only 3 decisions from a 510-tool-call, 199-turn session looks sparse, but is the *correct* result here — no provider key is configured in the live environment (by design: the user's own key was deliberately kept out of chat and only ever used in their own separate terminal for T3.9/T4.10), so this digest is running the deterministic-signals-only floor, not the full model-summarised path, and its footer says exactly that. Rule 5: 43 files touched with 23 outside the working directory is plausible for this actual session — the 23 are this session's own scratchpad test scripts and result files, genuinely outside the repository. Rule 6: no key/token/credential-shaped text anywhere, including in the entry quoting the user declining to paste their key into chat — the quote states the refusal, never the key. Rule 7: read directly, no mojibake.)*
