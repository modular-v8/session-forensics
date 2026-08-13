# spec: session-forensics — running decision digest for coding sessions

## outcome

While you work with a coding agent, a short digest of what was decided, what was rejected, and why is maintained continuously at `.decisions/<session-id>.md` inside the repository. It is never more than a few turns out of date, it survives a crash or a Ctrl+C because it was already written before the session ended, and it is short enough to read rather than skim. Across dozens of sessions, one command merges every digest in a project into a single chronological decision log — which is the actual job: writing a report about an application built over many sessions, where the reasoning behind each choice currently lives only inside multi-megabyte transcripts nobody will reopen.

**This supersedes a deterministic design that was built and measured.** A regex-and-heuristics extractor was implemented, run across a 26-transcript corpus, and found insufficient: four of 26 sessions produced no output at all, and in the session that designed this tool, six heuristics were cut on evidence — the most consequential decisions of that session — without tripping a single signal. Structural extraction reliably finds that a question was answered. It cannot find that someone changed their mind in prose. The measurements are preserved in `docs/signals.md`; the conclusion is that a language model must do the summarising, and the deterministic layer's job is to make that call small, cheap and safe.

## in scope

- A running digest updated **during** the session, so reliability no longer depends on any single end-of-session trigger firing.
- A deterministic delta extractor: given a transcript and a checkpoint, produce a compact, redacted payload of only what is new.
- Summarisation through a small provider abstraction over `urllib`: Gemini as primary, OpenRouter as fallback, each behind an adapter, with model identifiers as configuration strings.
- Redaction applied **before the payload is built**, because the failure mode is now transmission rather than disclosure on disk.
- A per-project opt-out marker that switches a project to deterministic-only output with nothing transmitted.
- Fixed-section output — Decided / Rejected / Open — with hard caps on entry count and entry length, enforced in code and not left to the model.
- `.decisions/` at the repository root, carrying its own `.gitignore` so it ignores itself.
- An aggregate command that merges every digest in a project into one chronological decision log.
- A `SKILL.md` that reads existing digests and runs the aggregate, and never writes.
- A per-session API call cap, after which the digest continues from structured facts alone.
- Distribution as a Claude Code plugin, with a documented manual `settings.json` block.
- A `.env` file at the repository root as an optional, lower-precedence source for provider keys (config-file support reversed post-ship, see plan.md § Tech Stack — the original "environment variables only" line below no longer holds).

## out of scope

- **Zero-token operation.** Explicitly abandoned. The previous design's headline claim was that summarisation cost nothing; it was true and the output was not worth reading. Cost is now accepted and bounded instead of eliminated.
- **A rolling project-level digest that every session updates.** Deferred to v2. The aggregate command produces the same artifact on demand without cross-session write conflicts.
- **Forcing a refresh from the skill.** The hook is the only writer. A second write path to the same file is where idempotency bugs live.
- **Non-Windows platforms.** Deferred to v2.
- **Transcript formats other than Claude Code's.** The output location and the model call are agent-agnostic; the parser is not.
- ~~**A configuration file.** Environment variables only in v1.~~ **Reversed post-ship** (tasks.md T4.12): a real, persistent OS environment variable required a `setx` plus a full Claude Code restart, reported directly as real setup friction for a tool meant to need minimal ceremony. `.env` support was added instead — see the in-scope list above and plan.md § Tech Stack for why this didn't mean adopting a dependency.
- **Retaining the cut heuristics.** Six were cut on measured evidence and are documented in `docs/signals.md` § 5 so they are not re-proposed.

## users & context

The primary user is the author: an experienced developer on Windows 10 running Claude Code daily across many small projects, comfortable editing `settings.json` and supplying an API key. The tool runs without being asked, and is read when a session ends or when a report is due.

The deciding use case is **writing up an application built across dozens of sessions**. That is what makes crispness a requirement rather than a preference — a digest nobody rereads is worth nothing — and what makes the aggregate command part of v1 rather than a nicety. Twenty-six digest files and no way to combine them would leave the original problem in place.

The secondary audience is developers who find the public repository. v1 serves only the Windows subset of them, and the README must say so above the fold.

## constraints

- **Stack:** Python 3.11+, standard library only. `urllib` covers the HTTP call, so no SDK and no `pip install`.
- **Windows 10+ only for v1.** No WSL, no Git Bash, no POSIX-only shell constructs. Detachment uses Windows process creation flags, never `nohup` or `disown`.
- **The Stop hook must not delay the user's next turn.** It validates, decides, spawns, and exits — everything else happens in a detached process.
- **Every hook entry point exits 0**, in every circumstance, including unhandled failure. A digest tool must never break a session.
- **Hooks run from the project root**, so every path the tool touches is absolute.
- **State passes between hook invocations through files**, keyed on session id. Environment variables do not survive across them.
- **UTF-8 is pinned explicitly** on every file, stream and request body. A Windows console defaults to cp1252 and will raise on an arrow or an em dash.
- **Nothing is transmitted before redaction.** Redaction is not a formatting step applied to output; it runs while the payload is assembled.
- **The raw transcript is never sent.** Only the extracted, redacted delta.
- **API cost is bounded per session** by a configurable call cap.

## data & integrations

**Input — Claude Code transcript.** A JSONL file at `~/.claude/projects/<project-slug>/<session-id>.jsonl`, one JSON object per line, read by streaming. Reference scale from the measured corpus: largest 7.5 MB / 2,454 lines / 1,472 messages, and a session's file grows as it runs. Records carry `origin` and `promptSource` fields that state authorship directly, `toolDenialKind` for refusals, `interruptedMessageId` for interrupts, and `compactMetadata` giving exact token loss at each compaction. The record-type set is version-dependent and open-ended.

**Input — hook payload.** JSON on stdin carrying at minimum `session_id`, `transcript_path`, `cwd` and `hook_event_name`.

**Integration — two model providers behind one interface.** Both are plain HTTPS calls over `urllib`; neither needs an SDK.

| | Primary | Fallback |
|---|---|---|
| Provider | Gemini | OpenRouter |
| Schema | Google generative-language REST | OpenAI-compatible chat completions |
| Key | `GEMINI_API_KEY` | `OPENROUTER_API_KEY` |
| Chosen because | daily allowance comfortably exceeds the workload | one string away from many models when the primary is unavailable |

Gemini leads because the workload is 15–30 calls per session; a ~50-per-day ceiling is exhausted by two sessions, and a digest corpus written half by one model and half by another reads inconsistently when assembled into a report. Each adapter normalises its provider's response into the same shape: generated text plus exact token counts. Adding a third provider is a new adapter, not a change to the caller.

Both providers receive the same redacted payload, so the privacy requirements apply identically to each, and the README must name both as recipients.

**Output — one digest per session.** `<repo-root>/.decisions/<session-id>.md`, rewritten in place as the session progresses. The directory contains a `.gitignore` holding `*` and `!.gitignore`, written and verified by the tool.

**Output — an aggregate.** A single merged decision log across all digests in a project, produced on demand, written where the user asks.

**State — a per-session sidecar.** `<repo-root>/.decisions/.state/<session-id>.json` recording the checkpoint reached, entries already accepted, API calls made, tokens spent, and the timestamp of the last successful update.

## prior decisions

- **The model does the summarising; the deterministic layer makes the call small.** Measured across 26 transcripts, structural signals miss the decisions that matter most. The extractor's job is now to produce a compact, redacted, authorship-checked delta — not to draw conclusions from it.
- **Updating during the session replaces trigger reliability as a problem.** The previous design depended on `SessionEnd`, which does not fire on Ctrl+C, a terminal close, or a crash. A digest that is already written cannot be lost by a trigger that never arrives. This removes the largest unresolved risk in the previous plan rather than mitigating it.
- **The model emits only new entries; the tool assembles the document.** Re-summarising the whole session on every update would grow in cost and drift as earlier detail is repeatedly rewritten. Each call sees the delta and the existing entry titles, and returns additions only.
- **Authorship is resolved at two levels before anything is sent.** Turn origination from transcript fields, block quotability from a content catalogue. Measured at zero leakage across 322 blocks; without it, harness-injected text reaches the model labelled as the user's own words.
- **Redaction runs before transmission, not before writing.** Under the previous design the risk was committing secrets to git. Now text leaves the machine, and the bar is higher.
- **A per-project opt-out marker.** The measured corpus contains job applications and financial records. Requiring the user to remember which directories are sensitive is a control that fails quietly.
- **Two providers behind one adapter interface, Gemini leading.** Provider daily limits, not token price, are the binding constraint at 15–30 calls per session. Gemini's allowance fits the workload; OpenRouter's does not, but it keeps many models one string away when the primary is unavailable. The abstraction is what makes "expand to cheaper options later" a new adapter rather than a rewrite.
- **Failover only on conditions the other provider might survive** — rate limit, quota exhaustion, server error. A malformed payload or an aborted redaction would fail identically anywhere, so retrying it elsewhere only doubles the latency of a doomed update.
- **A consistent model across a session's digests.** A corpus written half by one model and half by another reads inconsistently once assembled into a report, which is the deliverable this exists for.
- **Failures preserve the last good digest and retry on the next trigger.** The file always exists and is never corrupted by a network error; only its currency degrades, and it says so.
- **Output structure is enforced in code, not requested in a prompt.** Caps that exist only as prompt instructions are suggestions.
- **The hook is the only writer.** The skill reads and aggregates.
- **Windows only, plugin plus manual fallback, stdlib only.** Carried forward unchanged.

## requirements

### always active

- The system SHALL be implemented in Python 3.11+ using only the standard library.
- The system SHALL read transcripts by streaming one JSON object per line, and SHALL process a 2,454-line, 7.5 MB transcript without loading it whole.
- The system SHALL return control to the invoking hook within 1 second, performing all extraction, network and write work in a detached process that survives the parent's exit.
- The system SHALL detach using `subprocess.Popen` with the `DETACHED_PROCESS` and `CREATE_NEW_PROCESS_GROUP` creation flags and all standard streams directed to the null device, without invoking a shell.
- The system SHALL exit 0 from every hook entry point in every circumstance, including unhandled internal failure.
- The system SHALL resolve authorship at two levels — turn origination from transcript fields, block quotability from content classification — and SHALL NOT treat either as a substitute for the other.
- The system SHALL NOT transmit or quote any block belonging to a turn the transcript records as non-human.
- The system SHALL NOT transmit assistant reasoning blocks, file contents, or raw command output; those are reduced to counts, paths and exit states.
- The system SHALL apply redaction to every string in the request payload before the request is constructed.
- The system SHALL pin UTF-8 explicitly on every file, stream and request body.
- The system SHALL write the digest atomically via a temporary file and rename, keyed on session id.
- The system SHALL maintain the digest in three fixed sections — Decided, Rejected, Open — and SHALL enforce the configured caps on entries per section and words per entry by truncation in code, independently of the model's output.
- The system SHALL record in the digest footer the number of API calls made, the tokens consumed, the model used, and the timestamp of the last successful update.
- The system SHALL treat the transcript field set as version-dependent, requiring no field to be present, and SHALL degrade to a reduced digest rather than failing when one is absent.
- The system SHALL use absolute paths throughout.
- The system SHALL write diagnostics to a log file inside the ignored output directory, never to stdout or stderr from a hook context.

### event-driven

- WHEN the `Stop` hook fires, the system SHALL compare the transcript against the stored checkpoint and SHALL perform an update only if the unprocessed delta exceeds the configured size or turn threshold.
- WHEN the `SessionEnd` or `PreCompact` hook fires, the system SHALL perform an update regardless of threshold.
- WHEN an update runs, the system SHALL send only the unprocessed delta together with the titles of entries already accepted, and SHALL request additions rather than a rewrite of the existing digest.
- WHEN the model returns entries, the system SHALL append those not already present, SHALL preserve existing entries unchanged, and SHALL advance the checkpoint only after the digest is written successfully.
- WHEN the output directory does not exist, the system SHALL create it and write a `.gitignore` containing `*` and `!.gitignore` before writing any digest.
- WHEN a project contains the opt-out marker, the system SHALL transmit nothing, SHALL produce a digest from structured facts alone, and SHALL state in that digest that summarisation was disabled for the project.
- WHEN a provider returns a rate-limit, quota-exhausted or server-error response, the system SHALL attempt the same update once through the fallback provider, and SHALL record in the digest footer which provider produced each update.
- WHEN a provider fails for any other reason — malformed response, authentication error, aborted redaction — the system SHALL NOT attempt the fallback, since the same request would fail identically there.
- WHEN the per-session API call cap is reached, the system SHALL stop calling any provider, SHALL continue updating the digest from structured facts, and SHALL state in the digest that the cap was reached.
- WHEN a compaction boundary is present, the system SHALL report the tokens dropped and mark content before the earliest boundary as recoverable only in summarised form, taking the maximum of the cumulative figure rather than summing across boundaries.
- WHEN the aggregate command runs, the system SHALL merge every digest in the project into one chronologically ordered document, deduplicate entries that repeat across sessions, and attribute every entry to its source session.
- WHEN the skill is invoked, the system SHALL read existing digests or run the aggregate, and SHALL NOT write a digest or call the model.

### unwanted behavior

- IF the API call fails, times out, returns an error status, or returns unparseable content, the system SHALL leave the existing digest unchanged, SHALL NOT advance the checkpoint, SHALL record the failure and the number of unprocessed turns in the digest footer, and SHALL retry on the next trigger.
- IF no provider key is present in the environment, the system SHALL produce a deterministic-only digest, SHALL state why, and SHALL NOT attempt a network call.
- IF only one provider's key is present, the system SHALL use that provider and SHALL NOT treat the missing fallback as an error.
- IF both providers fail for the same update, the system SHALL leave the digest unchanged, SHALL NOT advance the checkpoint, and SHALL record both failures in the footer.
- IF the `.gitignore` covering the output directory cannot be written or verified, the system SHALL write no digest, SHALL log the refusal, and SHALL exit 0.
- IF redaction raises, the system SHALL abort the update and transmit nothing.
- IF a transcript line fails to parse, the system SHALL skip it, count it, continue, and report the count in the digest.
- IF the transcript is missing, unreadable or empty, the system SHALL log and exit 0 without writing.
- IF two updates for the same session run concurrently, the system SHALL ensure the atomic write leaves a complete, valid file.
- IF an unhandled exception occurs anywhere, the system SHALL catch it at the top level, log the traceback, and exit 0.
- IF the model returns an entry longer than the configured cap, the system SHALL truncate it rather than dropping it.
- IF no decisions are found for a session, the digest SHALL say so explicitly rather than containing invented narrative.

## risks & open questions

- **Incremental drift is the central new risk.** Appending entries across many updates can produce a digest that is accurate per entry but incoherent as a whole — duplicates phrased differently, superseded decisions sitting beside the ones that replaced them. The append-only design bounds cost and prevents rewriting history, but it does not solve coherence. A consolidation pass at session end is the intended mitigation and is unvalidated.
- **Threshold tuning is unmeasured.** The delta size and turn count that trigger an update have no validated values. Too low and cost climbs for no gain; too high and the digest is stale when a session dies.
- **Digest quality on small deltas is unmeasured.** A model given three turns of context may not be able to tell a decision from a passing remark. It may be that quality requires more context than cost prefers.
- **Content is transmitted to third parties — now two of them.** Redaction and the opt-out marker reduce the exposure; they do not eliminate it, and redaction catches key-shaped strings rather than a sentence describing something confidential. Each provider has its own retention and training policy, and the failover path means a given session's content may reach either. The README must name both recipients rather than describing "an API".
- **Provider daily limits, not token cost, are the binding constraint.** The per-session call cap must be set against the primary's daily allowance, not against a monthly spend. A cap of 40 calls per session against a 50-per-day ceiling exhausts the day in one session — the interaction between these two numbers is easy to get wrong and needs checking whenever either changes.
- **Two schemas to maintain.** The adapters normalise two different request and response shapes. A provider changing its API breaks one path silently while the other keeps working, which is exactly the kind of failure that goes unnoticed until the fallback is needed.
- **`Stop` hook frequency at scale is untested.** It fires after every assistant turn. The threshold check must be genuinely cheap, since it runs on a path the user is waiting on.
- **Deduplication in the aggregate is unspecified beyond intent.** Whether two similarly worded decisions from different sessions are the same decision is a judgement the tool will sometimes get wrong.
- **Cost per session is unmeasured.** The README figure must come from a real run.
- **Validation scope remains one user, one machine, one platform.** Every measurement in `docs/signals.md` comes from a single person's sessions on Windows with one Claude Code version.

## acceptance criteria

- [ ] With a valid key, running a real session produces `.decisions/<session-id>.md` that updates during the session, verified by reading the file mid-session and again later.
- [ ] Killing a session with Ctrl+C leaves a digest on disk covering everything up to the last update.
- [ ] `git status` in a repository that has run the tool shows no untracked digest files.
- [ ] Removing the `.decisions/.gitignore` and re-running results in no digest being written, plus a log entry explaining why.
- [ ] The digest never exceeds the configured caps, verified against a session that produced more raw entries than the cap allows.
- [ ] A session with no decisions produces a digest that says so and contains no invented narrative.
- [ ] Every hook entry point returns exit code 0 under: missing transcript, absent API key, unwritable output directory, malformed stdin payload, network failure, and a deliberately raised internal exception.
- [ ] The `Stop` hook returns control in under 1 second, measured on the largest transcript in the corpus.
- [ ] With the network disabled, an update leaves the previous digest intact, does not advance the checkpoint, and records the failure in the footer; restoring the network and triggering again incorporates the missed turns.
- [ ] A project containing the opt-out marker transmits nothing, verified by inspecting outbound requests, and still produces a deterministic digest.
- [ ] The call cap is reached on a long session, after which the digest continues updating and states that the cap was hit.
- [ ] The default call cap multiplied by a realistic number of sessions per day stays inside the primary provider's daily allowance, and the README states both numbers.
- [ ] Forcing a rate-limit response from the primary provider causes exactly one fallback attempt, and the footer names which provider produced the update.
- [ ] Forcing a malformed response from the primary causes no fallback attempt.
- [ ] With only one provider key present, updates succeed and the absent fallback is not reported as an error.
- [ ] Both adapters return the same normalised shape — generated text plus real token counts — verified by swapping providers on the same delta.
- [ ] A payload built from a transcript seeded with key-shaped strings contains no unredacted match, verified on the request body rather than on the digest.
- [ ] No payload contains file contents, raw command output, reasoning blocks, or text from a turn recorded as non-human.
- [ ] The aggregate command run across the 26-transcript corpus produces one ordered document in which every entry names its source session.
- [ ] The skill reads and aggregates without writing a digest or calling the model, verified by checking that no digest file changes when it runs.
- [ ] The digest footer reports real measured token counts from the API response, never estimates.
- [ ] Installing via the plugin path and via the manual `settings.json` path both produce a working hook on a Windows machine that has never run the tool.
- [ ] The README states Windows-only support above the fold, publishes a measured per-session cost and call count, and names both providers as recipients along with exactly what is transmitted and what is not.
