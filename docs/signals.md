# Signals → Decisions

Phase 0 recon output. Everything here comes from reading real transcripts and verifying each claim against the file with a parser — no signal is listed because it seemed plausible.

**Deep-read sample: 2 transcripts. Corpus available: 26 (~34 MB).** A and B were hand-read and drove signal discovery. The remaining 24 are the measurement set — signals are *found* in rich sessions and *measured* on unseen ones, and conflating the two is what produced the 53% filter.

Transcript B falsified five conclusions drawn from A alone. Assume the corpus falsifies more.

---

## 1. Transcript inventory

| | Transcript A | Transcript B |
|---|---|---|
| Project | `Cleaner-Agent` | `Personal-Finance-Tracker` |
| Session | `04b9fc46…` | `0abbae48…` |
| Size | 2,371,247 bytes | 7,482,869 bytes |
| Lines | 857 | 953 |
| Unparseable lines | 0 | 0 |
| Session kind | design / specification | build / debug |
| Tool calls | 143 | 191 |
| Tool errors | 4 (2.8%) | 6 (3.1%) |
| Dominant tools | Edit 41, Write 30, Bash 29 | Bash 68, Edit 25, browser MCP ~34 |
| Assistant visible text | 46,008 chars / 63 blocks | 31,651 chars / 107 blocks |
| Reasoning content | 88,915 chars / 92 blocks | **0 chars / 113 blocks** |
| Human-authored text | **7,826 chars / 31 msgs** | **3,321 chars / 9 msgs** |

Reference figures for the Phase 1 performance check come from the 680-message transcript, which is still outstanding.

**Note the file-size-to-line-count ratio.** B is 3.2× A's bytes across a similar line count — its records are far longer, because browser and Bash results carry large payloads. Line count is not a proxy for parse cost.

### Corpus (26 transcripts, ~34 MB)

Not hand-read. Used for measurement, rare-signal counts, and precision on unseen data.

| Role | Transcript | Lines | Msgs | Tools | Compactions |
|---|---|---|---|---|---|
| **C — scale + compaction** | `7905601a` | 2,454 | 1,472 | 493 | **4** |
| **D — third session kind** | `53aa5de4` | 356 | 209 | **72** | 0 |
| Short sessions | 14 files | <250 each | — | — | — |
| Paired A/B runs | `*-with-skill` / `*-without-skill` | — | — | — | — |

**C** is larger than A and B combined by line count and carries four compaction boundaries — it replaces the "680-message compacted session" the plan originally called for.

**D** is 5.2 MB across only 356 lines with 72 tool calls: a **writing** session, matching neither `design` nor `build/debug`. Expected to break the two-kind taxonomy in § 7, which is why it is in the set.

**Fourteen sessions under 250 lines.** Neither A nor B exercises the short-session path, where "no turnarounds detected" must read as a correct result rather than a broken tool.

### Provenance restriction

Transcripts under `Personal Dokumente\Job Bewerbungen`, `Personal Finance Tracker`, and other personal directories are usable for local measurement only. **No committed fixture, example, or README excerpt may derive from them.** The CI smoke fixture is hand-built or drawn from the `AI Projects` directories and sanitised regardless.

---

## 2. Record schema, as observed

Field names below are copied from the file, not recalled.

**Record types** — the set is **open-ended and differs per session.** Union of 12 across two transcripts; intersection of 6. Any parser that enumerates types will break on the third session.

| Type | A | B | Carries a message |
|---|---|---|---|
| `assistant` | 298 | 411 | yes |
| `user` | 184 | 221 | yes |
| `attachment` | 54 | 49 | no |
| `last-prompt` | 61 | 58 | no |
| `ai-title` | 53 | 57 | no |
| `mode` | 51 | 58 | no |
| `system` | 25 | 11 | rarely |
| `queue-operation` | 72 | — | no |
| `custom-title` | 59 | — | no |
| `permission-mode` | — | 58 | no |
| `file-history-snapshot` | — | 27 | no |
| `frame-link` | — | 3 | no |

**`frame-link`** records a publication event — a local file pushed to a `claude.ai/code/artifact/…` URL. Both a decision worth capturing and a privacy-relevant fact.

**`file-history-snapshot`** looked like a direct file-state ledger and would have been a better revert signal than string matching. It is not: `trackedFileBackups` is `{}` in every sample. Re-check on a session where a file was actually restored.

**Top-level fields** and presence count:

| Field | Present on | Notes |
|---|---|---|
| `type`, `sessionId` | 857 | always |
| `timestamp` | 633 | **optional** — never assume present |
| `uuid`, `parentUuid`, `isSidechain`, `userType`, `entrypoint`, `cwd`, `version`, `gitBranch` | 561 | present together |
| `message` | 482 | absent on metadata records |
| `requestId` | 298 | assistant only |
| `slug` | 249 | |
| `promptId` | 184 | |
| `toolUseResult` | 143 | structured result, separate from message content |
| `sourceToolAssistantUUID` | 143 | links a result to its call |
| `operation` | 72 | queue-operation only |
| `lastPrompt`, `leafUuid` | 61 | |

**Fields seen only in B:** `session_id` (653) — snake_case, coexisting with `sessionId` (926) in the same file; `attributionSkill` (90 — values `dataviz`, `artifact-design`); `attributionMcpServer` / `attributionMcpTool` (183); `permissionMode` (67).

`gitBranch` can be `HEAD` on a detached checkout. The branch line needs a sanity check, not a raw copy.

**Message content block types:** `text`, `tool_use`, `tool_result`, `thinking`.

**Reasoning content is not guaranteed.** B's 113 `thinking` blocks all carry an empty `thinking` field and a 432–948 char `signature`. A's 92 blocks carried 88,915 characters. Reasoning mining is opportunistic — nothing may depend on it being present.

### Authorship: two levels, two different questions

24 of 26 transcripts carry authorship fields:

```
promptSource : typed | suggestion_accepted | system
origin       : {kind: human} | {kind: task-notification} | ...
```

An earlier draft of this document claimed A and B predated these fields. **That was wrong** — it came from reading a truncated key census. Coverage is partial in some transcripts and sparse in B, but present nearly everywhere.

The field does **not** replace the block catalogue. They answer different questions at different levels, and conflating them was the source of every apparent disagreement between the two:

| Level | Source | Question | Governs |
|---|---|---|---|
| **Turn** | `origin.kind`, `promptSource` | Did this turn originate from the human? | positional signals, adjacency, turn sequencing |
| **Block** | pattern catalogue | May this text be quoted verbatim? | redaction, the category gate |

A single human turn routinely contains both — your typed text *and* an `<ide_opened_file>` stub the harness attached. The turn is human; the stub is not quotable. Both classifications are correct simultaneously.

### T0.6a — measured precision

Full population, all 24 transcripts with fields, block-level filter scored against turn-level ground truth:

```
TP = 194    FP = 1        precision (human) = 99.5%
FN =   5    TN = 8        recall    (human) = 97.5%
```

**All five false negatives are the level mismatch above**, not errors: three `<ide_opened_file>` stubs inside two-block human turns, one `<create-pr-command>` expansion, one 4,005-char pasted HTML file.

**The single false positive is the important result.** In a `promptSource=system` record:

> "Check on the two exploration agents (cv-tailor skill structure + Cleaner Agent multi-agent pattern) and continue drafting the plan once both have reported back."

Hand-adjudicated: the user did not type it. It is harness-generated continuation text carrying **no marker, tag, or stylistic tell** — it simply reads as human prose.

**This class is undetectable by pattern matching.** The field is the only defence. A summary built from a transcript without authorship fields therefore carries a category of error that nothing in the tool can find, and must say so rather than presenting inferred authorship as read authorship.

### Attached content in human turns

Adjudicated policy for turns marked `origin=human` whose content is supplied rather than written — pasted files, slash-command expansions, IDE stubs:

**Human turn, non-quotable block.** The turn counts for adjacency and positional signals so the turn sequence stays intact; the block is never quoted and is reported as a fact instead — "attached a 4,005-char HTML file" rather than four thousand characters of markup in a summary sitting in the repository.

### Other fields new in C

| Field | Use |
|---|---|
| `toolDenialKind` | `user-rejected` — the user refused a tool call. A decision, structurally recorded. Signal A8. |
| `isApiErrorMessage` | Separates API errors from genuine tool failures. The de-noiser A3 needs. |
| `interruptedMessageId` | Structural interrupt pointer; preferred over matching `[Request interrupted…]`. |
| `compactMetadata` | See below. |
| `logicalParentUuid` | Threading across a compaction boundary. |
| `file-history-delta` + `backup` + `trackingPath` | Points at an external backup file, not inline content. Not a revert ledger as hoped; `backupFileName` was `None` in every sample. Re-check in v2. |

Also seen: `agentName`, `classifierMetaLines`, `durationMs`, `effort`, `messageCount`, `origin`, `pendingBackgroundAgentCount`, `promptSource`, `snapshotMessageId`, `isApiErrorMessage`, `toolDenialKind`.

**The field set grows between Claude Code versions.** Three transcripts three weeks apart produced three different field sets. Nothing may require a field to exist.

### Compaction is fully quantified

`compactMetadata` on transcript C:

```
trigger: manual        preTokens: 338,064     postTokens: 21,277
cumulativeDroppedTokens: 316,787              durationMs: 190,115
preservedSegment: {headUuid, anchorUuid, tailUuid}
```

Four compaction boundaries at lines 826, 1306, 1663, 2438, with summaries of 28.9k / 21.8k / 34.4k / 30.9k characters. 34% of records precede the first boundary.

**The exact token loss is reportable.** "316,787 tokens dropped at compaction" is a stronger honest-limitations line than any prose disclaimer, and `preservedSegment` identifies precisely which records survived.

### Three schema facts that change the design

**`gitBranch` and `cwd` are top-level fields.** Branch detection needs no `git` subprocess. The git integration in `plan.md` drops to `check-ignore` only.

**Tool results arrive as `role: user` records.** Of 184 user records, 143 are tool results and 41 are text. Treating `role == "user"` as "the human typed this" would quote 143 tool-result payloads as user speech.

**`role: user` text is mostly not human either.** In A, 90% of user-text characters were harness-injected. The injected catalogue below is the union across both transcripts — **and it must be treated as incomplete.**

| Injected content | Recognised by | A | B |
|---|---|---|---|
| Skill load, headered | opens `Base directory for this skill:` | 1 | 1 |
| Skill body, unheadered | prose block matching a known skill's opening | — | 1 |
| Compaction summary | opens `This session is being continued from a previous conversation` | 1 | 1 |
| Task notifications | `<task-notification>` wrapper | 4 | — |
| Local-command scaffolding | `<local-command-caveat>`, `<command-name>`, `<local-command-stdout>` | 3 | 9 |
| Interruption marker | exactly `[Request interrupted by user]` | 1 | — |
| **Image attachment stub** | `[Image: original WxH, displayed at WxH. Multiply coordinates by N…]` | — | **8** |
| **Bare slash command** | message is exactly a `/command` token | — | **1** |
| **Human-authored** | remainder | **31 / 7,826 ch** | **9 / 3,321 ch** |

### Corpus-wide counts after the catalogue fix

Extended catalogue (adding image stubs, bare slash commands, and tag-openers) run across all 26 transcripts:

**200 human messages, 117 injected, 1 detectable false positive.**

| Injected category | Corpus count |
|---|---|
| `local_cmd` | 51 |
| `skill_load` | 20 |
| `compaction` | 9 |
| `task_notification` | 8 |
| `interrupt` | 8 |
| `image_stub` | 8 |
| `tag_open` | 7 |
| `slash_cmd` | 6 |

The one surviving false positive is an 8,899-char skill body carrying no recognisable header. Detection for that class is unsolved.

**Caveat on the "1 false positive" figure.** It comes from an automated suspicion pass that only catches certain shapes, so it is an upper bound on *detected* errors, not a measured precision. Hand-verification of a sample is still required — see `tasks.md` T0.6a.

**"Very long" is not a tell.** Three long messages were flagged as suspicious; two were genuinely human, including the 8,585-char brief that opened this project. Length does not separate a person from a skill body.

**Rare signals need corpus-scale counts.** Interruption markers scored 1 in A and 0 in B, but **8 across the corpus**. Two transcripts cannot measure a rare signal — and A6 is in the same position.

### The filter's own precision is the finding

The A-derived filter, applied unchanged to B, classified **19 messages as human when 9 were.** 53% precision on unseen data, failing silently — no crash, just a summary attributing words to the user that the user never typed.

Two consequences:

1. The catalogue is a **maintained, tested list**, not a one-shot regex set. Every new transcript adds rows.
2. Precision on unseen data is the metric that matters. A filter measured only on the transcript it was built from tells you nothing.

The image stubs also caused **every false positive in the parameter-reversal signal** — `Multiply coordinates by 2.55` / `by 3.15` / `by 2.70` share the tokens *coordinates, displayed, image, multiply* and carry different numbers, so they pair combinatorially. The noise was upstream of the heuristic, not in it.

**Encoding.** Writing `→` to a cp1252 Windows console raised `UnicodeEncodeError` during recon. All file and stream I/O pins UTF-8 explicitly.

---

## 3. Signal → decision table

Tiers rank by evidence strength. Tier A needs no language at all; Tier C is model- and phrasing-dependent and ships as low-confidence.

Measured across four transcripts: **A** (design, 857 lines), **B** (build/debug, 953), **C** (coding at scale, 2,454), **D** (writing/browsing, 356).

### Tier A — structural

| ID | Signal | A | B | C | D | Verdict |
|---|---|---|---|---|---|---|
| A1 | `AskUserQuestion` call + result | 1 | 2 | **7** | 0 | **Ship.** Strongest signal in the set. Perfect precision, zero inference. |
| A5 | `Write` to a path already written this session | 5 | 1 | 3 | 0 | **Ship.** |
| A4 | Interruption — prefer `interruptedMessageId`, fall back to the text marker | 1 | 0 | 2 | 1 | **Ship.** |
| A8 | `toolDenialKind: user-rejected` — the user refused a tool call | — | — | **1** | — | **Ship. New.** A refusal is a decision, recorded structurally. |
| A2 | Parameter reversal — same entity, conflicting numbers, across human messages | **2** | 0 | 0 | 0 | **Ship, with a documented fire rate.** Tuned to 100% precision and 100% recall on known cases; see § 4a. Fires ~2× per 200 human messages, and has never fired outside the history it was tuned on. |
| A7 | `frame-link` publication event | — | 3 | — | — | **Ship.** Local file pushed to a public artifact URL. |
| A3 | Error, then a different action | 4/4 | 6/6 | **26/26** | 0/0 | **Cut as written.** Fires on 100% of errors in every transcript — it is an error list, not a heuristic. Re-scope to "error, then the same goal reached differently," de-noised by `isApiErrorMessage`. |
| A6 | Edit whose replacement restores an earlier edit's original | 0 | 1 | 0 | 0 | **Cut.** 1 hit across **246 edits**. |

### Tier B — positional

| ID | Signal | A | B | C | D | Verdict |
|---|---|---|---|---|---|---|
| B2 | Short human message after a long assistant turn | 6 | 3 | 4 | 0 | **Ship.** The only positional signal that holds up. |
| B1 | Human message with enumerated imperatives | 4/31 | 0/19 | 1/20 | 0/4 | **Cut.** A transcript-A artifact — it tracks how the user was writing that day. |
| B3 | Human message after a tool burst of ≥3 | 48% | 74% | 85% | 75% | **Cut.** Describes how agent sessions work; discriminates nothing. |

### Tier C — lexical move classes

**Cut.** Totals across the four transcripts: **19, 6, 2, 0.** Ninety percent of all hits come from transcript A, and every class scores zero in D. These patterns fingerprint one session's phrasing, not a recurring behaviour.

This also falsifies last round's conclusion that the Tier C *profile* could discriminate session kind — the profile is all zeros for both C and D. See § 7.

---

## 4. Worked example: the best turnaround in the file

Detected by Tier A parameter reversal. No lexical signal touches it.

| Event | Content |
|---|---|
| U29 | *"restrict the questions asked in Complex to 15"* |
| A46 | rewrites `complex.md` as a *"self-contained 15-question hard cap"* |
| U30 | *"Okay I understand the denseness in complex, increase its limit to 20"* |
| Present state | `questions/complex.md` caps at 20 |

Proposed → implemented → reversed → replaced, every step anchored to an event index. This is the shape the tool exists to produce, and it comes entirely from extracting `(entity, number)` pairs and finding contradictions.

---

## 4a. T0.6b — tuning A2 to usable precision

Four variants, measured across all 26 transcripts, adjudicated candidate by candidate.

| Variant | Candidates | TP | FP | Precision | Recall |
|---|---|---|---|---|---|
| Original, before the content filter was fixed | 103 in transcript B alone | — | ~all | unusable | — |
| Tight — 6-turn window | 3 | 3 | 0 | 100% | **50%** |
| Middle — 15-turn window | 6 | 4 | 2 | 67% | 100% |
| **Final** | **4** | **4** | **0** | **100%** | **100%** |

**What the tuning actually changed.** The original noise was never in the heuristic — it came from unfiltered image stubs upstream. Once those were gone, two defects remained, both with identifiable causes:

1. **List ordinals read as parameters.** *"3. In spec.md, club the…"* produced a candidate `simple 4 → 3`. Fixed by rejecting a number that begins a line and is followed by `.` or `)`.
2. **Entity tokens captured from too wide a window.** A 90-character window pulled in `tasks.md` as the entity for a number it had nothing to do with. Fixed by requiring the entity within 50 characters before or 30 after.

**The window was the load-bearing parameter.** At 6 turns precision was perfect but a real revision was missed — the tier caps changed over 20+ turns of conversation. Widening to 15 recovered it and exposed the two defects above, which were then fixable. Tuning precision first would have locked in the recall loss invisibly.

**True positives found:**

| Entity | Revision | Evidence |
|---|---|---|
| `simple` | 4-7 → 5 | *"limit the questions to 4-7 for simple"* → *"Ask 5 questions at MAX"*. Shipped skill: ≤5. |
| `complex` | 15 → 20 | § 4's worked example. Detected in three resumed sessions of the same history. |

### Honest limits on this result

- **Fire rate: 2 reversals per ~200 human messages.** This is a rare signal.
- **Both true positives come from the history A2 was tuned against.** Across the other 23 transcripts — ~34 MB, ~160 human messages — it fires zero times.
- **Recall is measured only against reversals found by hand.** Reversals nobody noticed are not counted, so 100% recall means "caught everything we know about," not "caught everything."

**Shipping decision: ship, with the fire rate documented in the README.** This is a recorded exception to the rule in `spec.md` that a signal must fire on data it was not derived from. The rule was written to keep noisy signals out; A2's weakness is rarity, not noise, and zero false positives across 23 independent transcripts is real evidence that its precision generalises even though its recall is unproven. The exception is recorded here so that it is a decision rather than an oversight.

## 4a-bis. T0.9 — the resolver, verified

`src/session_forensics/transcript/authorship.py` implements the two-level design. Run across all 26 transcripts, 322 text blocks inside `user` records:

| Turn origin | Block caught | Block quotable |
|---|---|---|
| HUMAN | 5 | **197** |
| NOT_HUMAN | 8 | 1 — blocked at turn level |
| UNKNOWN | 104 | **7** |

**Leakage — a quotable block from a turn known to be non-human — is 0.** That is the property the whole design exists to guarantee.

**The turn level earns its place on exactly one block.** In session `23184985`, a `promptSource=system` record whose text the catalogue would have passed as clean: the harness-generated prompt hand-adjudicated in § 2. One block in 322, and nothing else in the tool could have caught it.

**The block level earns its place on 112.** Including 5 inside turns the field confirms as human — editor context stubs, a command expansion, pasted markup — exactly the attached-content policy adjudicated in T0.6a.

### Authorship coverage is better than the raw field count suggests

111 of 322 blocks carry no authorship field, which looks like 34% exposure. It is not. Those blocks are overwhelmingly injected content the catalogue catches with confidence — 51 local-command, 20 skill-load, 9 compaction, 8 interrupt, 8 image-stub, 6 slash-command.

**Only 7 quotable blocks corpus-wide (2.2%) rest on the catalogue alone**, spread across 4 sessions. Authorship is field-verified for **197 of 204 quotable blocks — 96.6%**.

Consequence for the summary: report the proportion, not a boolean. "Authorship field-verified for 29 of 30 quoted passages" tells a reader something; a blanket "authorship was inferred" banner on a session where one block in thirty is unverified does not.

## 4b. T0.10 — corpus fire counts

26 transcripts · 203 human messages · 2,360 tool calls · 0 unparseable lines.

Ordered by **breadth** — the number of transcripts a signal fires in — because raw count rewards a signal that fires often in one session and never again.

| Signal | Fires | Transcripts (of 26) | Per 1k human msgs | Status |
|---|---|---|---|---|
| A1 question→answer | 60 | 18 | 296 | Ship. Dominant. |
| B2 short reply after long turn | 31 | 13 | 153 | Ship. |
| A5 write-after-write | 18 | 9 | 89 | Ship. |
| A8 user-rejected tool call | **7** | 7 | 34 | Ship, **narrowed** — see below. |
| A4 interrupt | 8 | 7 | 39 | Ship. |
| A2 parameter reversal | 4 | 3 files, **1 history** | 20 | Ship as a recorded exception — § 4a. |
| A7 publication event | 3 | **1** | 15 | Ship. Rare, not unproven — see below. |

**No signal scored zero, so none is cut by the T0.10 rule.**

### A8 was over-counting

`toolDenialKind` carries two values across the corpus: `user-rejected` (7) and `permission-rule` (3). A permission-rule denial is the harness automatically blocking an action under a configured rule — not a decision anyone made in the conversation. **A8 filters on the value, never on the field's presence**, which takes its true count from 10 to 7.

### A7 is rare, not unproven

A7 fires three times, all inside one transcript — the same breadth problem that made A2 an exception. The difference is that A7 reads a record type directly and infers nothing, so it cannot produce a false positive. It is documented as rare because `frame-link` records only exist when a file is published to an artifact URL, which most sessions never do.

### A1 is the centre of gravity

Sixty fires across 69% of transcripts, roughly double the next signal and fifteen times A2. **Decision capture, not turnaround detection, is where the output's mass sits.** The README should describe the tool in that order rather than leading with the rarer half.

### Both empty-path cases occur naturally

Four of 26 transcripts fire no signals at all, and two produce signals while containing **zero** human messages. The "no turnarounds detected" state and the "summary with no human text" state are not edge cases to simulate — they are already present in the corpus and must read as correct results.

## 4c. Compaction loss, measured

| Session | Boundaries | Tokens dropped | Peak pre-compaction |
|---|---|---|---|
| `7905601a` | 4 | **1,034,701** | 338,064 |
| Cleaner-Agent history | 1 | 228,999 | 245,321 |
| `0abbae48` | 1 | 145,968 | 161,011 |
| `23184985` | 1 | 93,769 | 106,409 |

**1,503,437 tokens dropped across four unique histories** (1,961,435 if the three resumed Cleaner-Agent files are counted separately).

**Counting caveat:** `cumulativeDroppedTokens` is already cumulative within a session, so summing it across a session's boundaries double-counts. Take the maximum per session. An earlier draft of this document reported 3.5M by making exactly that mistake.

## 4d. T0.7b — end-to-end over the corpus

The pipeline now runs: reader → adapter → authorship → facts → heuristics → render. All 26 transcripts, ~34 MB.

| Measure | Result | Requirement |
|---|---|---|
| Unparseable lines | **0 of 26 files** | report and continue |
| Slowest session (2,454 lines / 7.4 MB) | **0.26 s** | under 10 s |
| Peak memory, 7.5 MB input | **4.6 MB** | flat vs file size |
| Byte-identical across repeat runs | **yes** | deterministic |
| Sessions with zero candidates | **4 of 26** | must read as a result |
| Candidates total | 127 | — |

Peak memory on the largest file is *below* its size, which is the streaming guarantee holding.

### Corrected fire counts

| Signal | T0.10 | Now | Why |
|---|---|---|---|
| A4 interrupt | 8 | **10** | T0.10 took `max(field, text_marker)`; the two occur on *different* records, so the union is correct. |
| B2 | 31 | 33 | Turn-level rule now admits two blocks the earlier ad-hoc script dropped. |
| A1, A5, A8, A2, A7 | 60, 18, 7, 4, 3 | unchanged | — |

### Two defects found by rendering, not by counting

**A4 had no text-marker fallback.** The module read only `interruptedMessageId`, so on transcripts predating that field the signal silently reported 2 instead of 10. Counting scripts had masked it because they checked both paths.

**A1 rendered its own question back before the answer.** The question tool echoes each question alongside the selection, so quoting the raw payload repeated the entire question — on the signal carrying 60 of 127 candidates. Fixed by unpacking the pairs and quoting only the choice, keyed by its header.

### Three rendering fixes from reading the tool's own output

Running the tool on the session that built it surfaced three defects that no count would have shown:

**B2 titled every candidate with the signal's name.** Seven consecutive headings reading "Brief reply after a long turn", with the actual reply buried in the evidence. Candidates are now titled with their own content, as A1 already was.

**Scratch files were listed as project files.** Eight files under `AppData\Local\Temp` appeared in the same list as `spec.md` and the source modules, overstating what the session changed. Files are now split by whether they sit under the session's working directory, and project paths render relative to it.

**No sentence said what the session was.** The header table gives timestamps and counts but never answers "what was this?" for someone scanning a directory of summaries. A one-line mechanical strapline now opens each summary — shape, duration, tool volume, files touched, decision count — derived from counts alone, no model involved.

### The honest limitation this exposed

Session `6e5552f2` — 4.5 hours, 18 human messages, 127 tool calls, 39 edits across two files — produces **zero** decisions. The empty state reads correctly, and it is correct: nothing was refused, reversed, interrupted, or explicitly chosen. But a session that substantial containing no recoverable decision shows the signal set's recall on ordinary work is low.

Four of 26 sessions land here. The summary is still useful — activity, files, provenance, compaction loss — but the decisions section will be empty more often than the framing implies, and the README must say so.

## 5. Falsified hypotheses

Recorded because the honest-limitations section depends on them.

**Edit-restores-prior-`old_string` is marginal, not dead.** 0 hits in A, 1 hit in B, across 66 `Edit` calls total. It survives as a bugfix-only signal and cannot carry a turnarounds section.

**Error rate does not discriminate session kind.** A: 2.8%. B: 3.1%. The premise that coding sessions are error-dense is false. B's six errors are a CDP screenshot failure, a page with no text, `python3: command not found`, and a `FileNotFoundError` — environment noise, not abandoned approaches. Kind must be read from tool mix alone.

**The synthetic filter had 53% precision on unseen data.** Built from A, applied to B, it reported 19 human messages where there were 9. See § 2. This is the single most consequential result of the second transcript, and it generalises: any signal validated on the transcript it was derived from is unmeasured.

**B1 collapsed from 4/31 to 0/19.** Enumerated imperatives track how the human is writing, not what kind of session it is. A signal that depends on the user's prose style is a signal that will silently stop working.

**Reasoning content is absent in three of four transcripts.** A had 88,915 chars across 92 blocks. B, C and D have **0 chars across 360 blocks** — signature only. Transcript A is the outlier. Reasoning mining should be dropped from v1 rather than specified as opportunistic.

**Tier C was a single transcript's phrasing.** 19 hits in A, 6 in B, 2 in C, 0 in D. Cut.

**Four session-kind discriminators have now been proposed and falsified** — error rate, revert count, tools-per-text ratio, Tier C profile. See § 7. Each looked reasonable before measurement.

**A3 fires on 100% of errors in all four transcripts.** 4/4, 6/6, 26/26, 0/0. A heuristic that never declines is not detecting anything.

**Hand-transcribed phrases do not survive contact.** Five of eleven phrases recorded during hand-reading do not appear in the file at all: `Flagging` (0), `Judgement call` (0 — the file has `judgment call`), `That's a gap` (0 — apostrophe mismatch), `Fair critique` (0 — the file has "it's a fair critique"), `but at the same time` (0). The rest fire once each. Hand-transcription is unreliable at the character level, which is the argument for move classes over literal strings.

---

## 6. Decisions with no reliable signal

Required by `tasks.md` T0.2. These are the known recall gaps.

**Reasoning that never surfaced.** Alternatives weighed and discarded inside `thinking` blocks that never reached visible text. Per `spec.md`, thinking is mined for facts and never quoted — so a rejected approach named only there can be detected but not evidenced with its own words.

**Decisions made by silence.** The user reads a proposal, says nothing about one part, and it ships. Indistinguishable from agreement in the transcript.

**Terse redirection.** A user who corrects course by saying "no" or by simply issuing a different instruction leaves no lexical trace and may not trip a positional rule either. Expect recall gaps; prefer precision.

**Decisions imported from outside the session.** U36 references edits made to `README.md` in the GitHub web UI between sessions. The transcript records the consequence, never the decision.

**Pre-compaction content.** This session contains a `/compact` at line 483 with the argument `only highlight our important decisions`. Everything before it survives only as the compaction summary's paraphrase. The raw transcript is the input, so the earlier records are still on disk — but any session where compaction ran before the transcript was flushed is a known gap.

---

## 7. Session kinds

Four candidate discriminators have now been proposed and falsified.

| | A design | B build/debug | C coding at scale | D writing/browsing |
|---|---|---|---|---|
| Error rate | 2.8% | 3.1% | 5.3% | 0% | 
| Reverts | 0 | 1 | 0 | 0 |
| Tools per text block | 2.27 | 1.79 | **2.20** | **2.48** |
| Tier C profile | 19 hits | 6 | 2 | **0** |
| Human msgs / chars | 31 / 7,826 | 9 / 3,321 | 20 / 13,159 | **4 / 421** |
| Dominant tools | Edit 41, Write 30 | Bash 68, browser 34 | Edit 172, Bash 132 | browser 36, Read 13 |

**Falsified:** error rate (no ordering), revert count (near-zero everywhere), tools-per-text ratio (C at 2.20 and D at 2.48 are indistinguishable, for a heavy-coding session and a browsing one), Tier C profile (zero in C and D).

**Only tool composition separates the four.** Kind detection, if it ships at all, classifies on tool *categories* — edit tools, shell, browser, read-only — not on any ratio or rate.

**Transcript D is the extreme case worth remembering:** 5.19 MB, and the human typed **421 characters across 4 messages.** Almost the entire file is browser automation payload. Any summary of D is necessarily thin, and that is a correct result rather than a failure.

**Decisions live in prose in every kind observed.** The original premise — that a coding session's decisions would be recoverable from tool telemetry — is not supported by any of the four.

---

## 8. What this table still needs

- [x] Transcript B: a build/debug session. *Expectation was wrong — Tier A did not carry it, and Tier B thinned in a way unrelated to session kind.*
- [ ] Transcript C: the 680-message compacted session. Confirms performance figures and exercises the compaction gap.
- [ ] **Fix the synthetic catalogue, then re-measure A2.** Its precision is currently unknown, not bad — every measured false positive traces to an unfiltered image stub.
- [ ] **Precision, not just fire counts.** Each signal needs hand-verified true/false positives on a transcript it was not derived from. Fire count alone told us nothing about the filter that was 47% wrong.
- [ ] Re-check `file-history-snapshot` on a session where a file was genuinely restored.
- [ ] Decide whether `frame-link` publication events belong in the summary.
