"""Detached worker: orchestrates one update from transcript to written digest.

Built incrementally, in dependency order:
  T3.7  summarise_with_failover   provider failover
  T3.8  should_call_provider,     the call-cap / no-key gate, and the
        candidates_to_entries     structural-signal-to-entry fallback
  T4.5  run / main                the full pipeline: opt-out check, locate,
                                   lock, delta, provider, merge, render,
                                   write, checkpoint

Not imported by hookrunner.py, which spawns this module as a detached process
(`python -m session_forensics.worker <session_id> <transcript_path> <cwd>`)
rather than calling into it directly -- see plan.md's import allowlist for
hookrunner.py and tasks.md T4.6.
"""

from __future__ import annotations

import datetime
import sys
import tempfile
import time
import traceback
from pathlib import Path

from . import config, log, optout
from .digest.merge import accumulate_session_stats, merge_entries
from .digest.model import Digest
from .digest.prompt import ParsedEntry, build_prompt, parse_entries
from .digest.render import render
from .extract import facts as facts_mod
from .extract.delta import Delta, build_delta
from .extract.heuristics import Candidate
from .output import locate, lock as lock_mod, state as state_mod, writer
from .providers import gemini, openrouter
from .providers.base import Completion, ProviderError
from .transcript import claude_code

__all__ = [
    "summarise_with_failover",
    "should_call_provider",
    "candidates_to_entries",
    "run_over_transcript",
    "run",
    "main",
]


def summarise_with_failover(
    prompt: str,
    *,
    primary=None,
    fallback=None,
    primary_model: str | None = None,
    fallback_model: str | None = None,
) -> Completion:
    """Call the primary provider; on a retryable error, attempt the fallback
    exactly once. A terminal error never triggers a fallback attempt -- the
    same request would fail identically there (spec.md § requirements).

    `primary`/`fallback` default to the real `gemini`/`openrouter` modules;
    tests pass `providers.fake.FakeProvider` instances instead. Model names are
    resolved from `config` *inside* the function body, not as parameter
    defaults -- a default evaluated once at import time would defeat T2.1's
    "read fresh on every access" guarantee.

    If both attempts fail, the fallback's error is raised with the primary's
    error chained as `__cause__` -- spec.md requires recording *both* failures
    in the digest footer, and Python's native exception chaining already
    carries both without a bespoke combined-error type.

    When only the primary has a key configured, the fallback is never even
    attempted on a retryable failure -- the primary's error is re-raised
    directly. Measured directly (T3.9, against real Cleaner-Agent and
    Personal-Finance-Tracker sessions with only GEMINI_API_KEY set): attempting
    a keyless fallback anyway makes it fail with AuthError every time, and that
    AuthError -- not the primary's real, useful failure reason -- is what ends
    up in the digest footer. spec.md is explicit that a missing fallback key
    must never be treated as an error; surfacing it as the *reported* failure
    is exactly that, just one level removed.
    """
    primary = gemini if primary is None else primary
    fallback = openrouter if fallback is None else fallback
    primary_model = primary_model or config.model_primary()
    fallback_model = fallback_model or config.model_fallback()

    try:
        return primary.summarise(prompt, model=primary_model)
    except ProviderError as primary_error:
        if not primary_error.retryable:
            raise
        if not getattr(fallback, "has_key", lambda: True)():
            raise
        try:
            return fallback.summarise(prompt, model=fallback_model)
        except ProviderError as fallback_error:
            raise fallback_error from primary_error


def should_call_provider(digest: Digest) -> tuple[bool, str | None]:
    """Whether this update should attempt a provider call.

    Returns `(True, None)` to proceed, or `(False, reason)` where reason is
    `"no_key"` or `"cap_reached"` -- the two conditions spec.md routes through
    the same deterministic-only path as opt-out. Opt-out itself is handled
    earlier and is not this function's concern: it short-circuits before
    extract/delta.py is ever called (optout.py, tasks.md T2.6), so there is no
    Delta and no digest-update decision left to make by the time this would run.
    """
    if not (config.gemini_api_key() or config.openrouter_api_key()):
        return False, "no_key"
    if digest.calls >= config.call_cap():
        return False, "cap_reached"
    return True, None


#: Structural signal -> section, when there is no model to ask. A1 (question
#: answered) and A7 (published) are concrete actions someone took: decided. A8
#: (tool call refused) is an explicit rejection. A4 (interrupted) is something
#: left incomplete, not a settled choice: open. No inference beyond this fixed
#: mapping -- these four signals were kept in extract/heuristics.py precisely
#: because they read a transcript field and cannot be wrong (docs/signals.md § 3).
_CANDIDATE_SECTION = {"A1": "decided", "A7": "decided", "A8": "rejected", "A4": "open"}


def candidates_to_entries(candidates: list[Candidate]) -> list[ParsedEntry]:
    """The deterministic-only fallback: structural signals become entries
    directly, with no model involved. Used when `should_call_provider` says no,
    so a project that never calls a provider still gets a digest with real
    content in it rather than an empty shell. (The opt-out path is stricter
    still -- see `_process_optout_update` -- and never calls this at all.)
    """
    entries = []
    for candidate in candidates:
        section = _CANDIDATE_SECTION.get(candidate.signal)
        if section is None:
            continue
        turns = None
        if candidate.evidence:
            indices = [ev.index for ev in candidate.evidence]
            turns = (min(indices), max(indices))
        entries.append(ParsedEntry(section=section, text=candidate.title, why=None, turns=turns))
    return entries


def _apply_update(digest: Digest, delta: Delta, *, cwd: str | None, timestamp: str) -> bool:
    """Advance `digest` with one delta's worth of new material.

    Single source of truth for "what does one update actually do" -- shared by
    the real pipeline (`_process_update`, `_process_optout_update`) and the
    CLI replay harness (`run_over_transcript`), so a fix like T3.9's has-key
    bug only ever needs to happen in one place.

    Always folds `delta.facts` into the digest's running totals via
    `accumulate_session_stats`, even when `delta.turns`/`delta.candidates` are
    both empty: a stretch of pure tool activity with no human text and no
    structural signal still has tool calls and files touched worth counting in
    the strapline, even though there is nothing for a provider to summarise and
    no candidates to fall back to. A provider is asked (or the deterministic
    fallback used) only when `delta.is_empty` is False -- calling a model on a
    delta with nothing to say would just waste one of the per-session calls.

    Returns True if this succeeded and the caller should advance its
    checkpoint; False if a provider call failed, meaning the checkpoint must
    NOT advance, but `digest.last_error`/`turns_pending` are already set so
    the caller can still persist and render them (spec.md requires the failure
    recorded in the footer even though the digest's *content* is unchanged).
    """
    parsed: list[ParsedEntry] = []
    if not delta.is_empty:
        can_call, reason = should_call_provider(digest)
        if can_call:
            try:
                completion = summarise_with_failover(build_prompt(delta))
            except ProviderError as exc:
                digest.last_error = _describe_failure(exc)
                digest.turns_pending = len(delta.turns)
                return False
            digest.calls += 1
            digest.tokens_in += completion.tokens_in
            digest.tokens_out += completion.tokens_out
            digest.model = completion.model
            digest.provider = completion.provider
            digest.last_error = None
            parsed = parse_entries(completion.text, provider=completion.provider)
        else:
            digest.cap_reached = reason == "cap_reached"
            digest.no_key = reason == "no_key"
            parsed = candidates_to_entries(delta.candidates)

    merge_entries(digest, parsed, timestamp=timestamp)
    accumulate_session_stats(digest, delta, cwd=cwd)
    digest.turns_covered += len(delta.turns)
    digest.turns_pending = 0
    digest.last_success = timestamp
    return True


def _describe_failure(exc: ProviderError) -> str:
    """`type: message` for `exc`, plus the same for its chained cause if one is
    present -- spec.md requires recording *both* failures when both providers
    fail for the same update, and the cause is exactly where the primary's
    error lives when the fallback was the one that ultimately raised.
    """
    description = f"{type(exc).__name__}: {exc}"
    cause = exc.__cause__
    if isinstance(cause, ProviderError):
        description += f" (after primary failed: {type(cause).__name__}: {cause})"
    return description


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# CLI replay harness -- tasks.md T3.9 (quality validation) and T4.10
# (threshold measurement) run against this. Does not touch disk.
# ---------------------------------------------------------------------------

def run_over_transcript(
    transcript_path: str,
    *,
    session_id: str,
    cwd: str | None = None,
    chunks: int = 10,
    call_delay_seconds: float = 4.0,
) -> Digest:
    """Replay a whole transcript as a sequence of bounded updates -- several
    small deltas, the shape a real session actually produces, not one call
    covering everything. Splits the file into `chunks` roughly-equal line-count
    snapshots and processes each in turn; the checkpoint advances only after a
    successful update, exactly as a real run would (a provider failure leaves
    it where it was and the next chunk retries the same range with more added).

    This does not write anything to disk. It is the CLI's real (non-dry-run)
    `digest` path.

    `call_delay_seconds` sleeps before each real provider call (not before the
    deterministic-only path, which makes none). A real session's calls are
    naturally spaced by however long the user takes between turns; this replay
    fires them back-to-back instead, which measurably triggers Gemini's
    per-minute rate limit in a way normal usage does not -- found directly
    during T3.9 (every one of 10 rapid chunks failed with a retryable error,
    masked at the time by a since-fixed bug where the keyless fallback's
    AuthError overwrote the real one). Default 4s keeps ~10 chunks comfortably
    under a typical free-tier RPM ceiling; pass 0 to disable for fake-provider
    tests, where there is no real rate limit to respect.
    """
    total_lines = claude_code.parse(transcript_path).lines
    digest = Digest(session_id=session_id)
    if total_lines == 0:
        return digest

    chunk_size = max(1, total_lines // max(1, chunks))
    boundaries = sorted({min(total_lines, chunk_size * i) for i in range(1, chunks + 1)} | {total_lines})
    boundaries = [b for b in boundaries if b > 0]

    with open(transcript_path, encoding="utf-8", errors="replace") as source:
        all_lines = source.readlines()

    checkpoint_event = checkpoint_line = 0
    with tempfile.TemporaryDirectory(prefix="sf_replay_") as tmp:
        for i, boundary in enumerate(boundaries):
            if boundary <= checkpoint_line:
                continue
            snapshot = Path(tmp) / f"snapshot_{i}.jsonl"
            snapshot.write_text("".join(all_lines[:boundary]), encoding="utf-8")

            delta = build_delta(
                str(snapshot),
                checkpoint_event=checkpoint_event,
                checkpoint_line=checkpoint_line,
                existing_titles=[e.text for e in digest.entries],
            )
            if delta.range[1] == checkpoint_event and delta.checkpoint_line <= checkpoint_line:
                continue  # truly nothing new, not even a fact to accumulate

            if (
                call_delay_seconds > 0
                and digest.calls > 0
                and not delta.is_empty
                and should_call_provider(digest)[0]
            ):
                time.sleep(call_delay_seconds)

            timestamp = _now_iso()
            succeeded = _apply_update(digest, delta, cwd=cwd, timestamp=timestamp)
            if succeeded:
                checkpoint_event, checkpoint_line = delta.range[1], delta.checkpoint_line
            # else: checkpoint NOT advanced; the next (larger) chunk retries this range too

    return digest


# ---------------------------------------------------------------------------
# The real pipeline -- what hookrunner.py's spawned process actually runs.
# ---------------------------------------------------------------------------

def _write_digest(decisions_dir: Path, digest: Digest) -> None:
    writer.write_atomic(locate.digest_path(decisions_dir, digest.session_id), render(digest))


def _process_update(
    *, transcript_path: str, cwd: str, session_state: state_mod.SessionState,
    decisions_dir: Path, log_path: Path,
) -> None:
    digest = session_state.digest
    digest.optout = False  # reflects the current marker state; it may have been removed

    delta = build_delta(
        transcript_path,
        checkpoint_event=session_state.checkpoint_event,
        checkpoint_line=session_state.checkpoint_line,
        existing_titles=[e.text for e in digest.entries],
    )
    if delta.range[1] == session_state.checkpoint_event and delta.checkpoint_line <= session_state.checkpoint_line:
        log.debug(log_path, "nothing new since the last checkpoint; no write", session_id=digest.session_id)
        return

    timestamp = _now_iso()
    succeeded = _apply_update(digest, delta, cwd=cwd, timestamp=timestamp)

    _write_digest(decisions_dir, digest)

    if succeeded:
        session_state.checkpoint_event, session_state.checkpoint_line = delta.range[1], delta.checkpoint_line
    state_mod.save(session_state, locate.state_path(decisions_dir, digest.session_id))

    status = "succeeded" if succeeded else f"FAILED ({digest.last_error})"
    log.info(
        log_path,
        f"update {status}: checkpoint now ({session_state.checkpoint_event}, {session_state.checkpoint_line})",
        session_id=digest.session_id,
    )


def _process_optout_update(
    *, transcript_path: str, cwd: str, session_state: state_mod.SessionState,
    decisions_dir: Path, log_path: Path,
) -> None:
    """spec.md: transmits nothing and produces a digest from structured facts
    alone. Deliberately does not call extract/delta.py at all (tasks.md T2.6) --
    parses directly and hands `_apply_update` an empty-turns/empty-candidates
    pseudo-Delta, which by construction never reaches the provider-call or
    candidates_to_entries branches (`delta.is_empty` is always True here), only
    the fact-accumulation that runs unconditionally.
    """
    digest = session_state.digest
    digest.optout = True
    digest.no_key = False
    digest.cap_reached = False

    transcript = claude_code.parse(
        transcript_path,
        after_line=session_state.checkpoint_line,
        start_index=session_state.checkpoint_event,
    )
    last_index = transcript.events[-1].index if transcript.events else session_state.checkpoint_event
    if last_index == session_state.checkpoint_event and transcript.lines <= session_state.checkpoint_line:
        log.debug(log_path, "optout: nothing new since the last checkpoint; no write", session_id=digest.session_id)
        return

    pseudo_delta = Delta(
        turns=[], candidates=[], existing_titles=[],
        facts=facts_mod.extract(transcript),
        range=(session_state.checkpoint_event, last_index),
        checkpoint_line=transcript.lines,
        unparseable=transcript.unparseable,
        compactions=list(transcript.compactions),
        session_started=transcript.started,
        session_ended=transcript.ended,
        branch=transcript.branch,
    )

    timestamp = _now_iso()
    _apply_update(digest, pseudo_delta, cwd=cwd, timestamp=timestamp)  # always succeeds: no provider ever attempted

    _write_digest(decisions_dir, digest)
    session_state.checkpoint_event, session_state.checkpoint_line = last_index, transcript.lines
    state_mod.save(session_state, locate.state_path(decisions_dir, digest.session_id))
    log.info(
        log_path,
        f"optout update: facts-only, checkpoint now ({session_state.checkpoint_event}, {session_state.checkpoint_line})",
        session_id=digest.session_id,
    )


def _run(*, session_id: str, transcript_path: str, cwd: str, fallback_log: Path) -> None:
    try:
        decisions_dir = locate.locate(cwd)
    except locate.LocateError as exc:
        log.error(fallback_log, f"write gate refused, no digest written: {exc}", session_id=session_id)
        return

    log_path = decisions_dir / "forensics.log"
    held = lock_mod.acquire(locate.lock_path(decisions_dir, session_id))
    if held is None:
        log.info(log_path, "another worker already holds the lock for this session; exiting", session_id=session_id)
        return

    try:
        session_state = state_mod.load(locate.state_path(decisions_dir, session_id))
        if session_state is None:
            session_state = state_mod.SessionState(digest=Digest(session_id=session_id))

        if optout.is_opted_out(locate.repo_root(cwd)):
            _process_optout_update(
                transcript_path=transcript_path, cwd=cwd, session_state=session_state,
                decisions_dir=decisions_dir, log_path=log_path,
            )
        else:
            _process_update(
                transcript_path=transcript_path, cwd=cwd, session_state=session_state,
                decisions_dir=decisions_dir, log_path=log_path,
            )
    finally:
        held.release()


def run(*, session_id: str, transcript_path: str, cwd: str) -> None:
    """The full pipeline. Never raises -- every failure mode is caught, logged,
    and leaves any existing digest untouched (spec.md: a digest tool must never
    break a session). This is what hookrunner.py spawns as a detached process
    (T4.6); see `main` below for the command-line entry point it targets.

    Logging destination depends on how far execution got: `output/locate.py`
    itself failing means `.decisions/` cannot be trusted, so that one failure
    (and anything before locate.py even runs) goes to a fallback log outside
    the repository entirely; everything else logs inside `.decisions/`, once
    it is known to exist.
    """
    fallback_log = Path(tempfile.gettempdir()) / "session_forensics" / f"{session_id}.log"
    try:
        if not Path(transcript_path).is_file():
            log.error(fallback_log, f"transcript not found: {transcript_path}", session_id=session_id)
            return
        _run(session_id=session_id, transcript_path=transcript_path, cwd=cwd, fallback_log=fallback_log)
    except Exception:
        log.error(fallback_log, f"unhandled exception:\n{traceback.format_exc()}", session_id=session_id)


def main(argv: list[str] | None = None) -> int:
    """`python -m session_forensics.worker <session_id> <transcript_path> <cwd>`
    -- the process hookrunner.py spawns detached, stdio to DEVNULL. Always
    exits 0: nothing is watching this process's exit code, and `run` already
    logs everything it can.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        generic_log = Path(tempfile.gettempdir()) / "session_forensics" / "malformed_invocation.log"
        log.error(generic_log, f"worker invoked with {len(args)} arg(s), expected 3 (session_id, transcript_path, cwd): {args!r}")
        return 0
    session_id, transcript_path, cwd = args
    run(session_id=session_id, transcript_path=transcript_path, cwd=cwd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
