"""Command line entry point.

  digest --dry-run <transcript>   print the Delta a real update would send (T2.7)
  digest <transcript>             real pipeline preview: calls a provider, prints
                                   the rendered digest. Writing to .decisions/ is
                                   Phase 4 (output/locate.py, output/writer.py);
                                   until then this is the tool T3.9's validation
                                   and T4.10's threshold measurement run through.
  aggregate --out <path>          merge every digest in a project into one document (T5.2)

This is also the primary development loop and the recovery tool for any session
the hooks miss (plan.md § Integration Plan): the pipeline is fully exercisable
from here with nothing but a transcript path, no hook involved.

Errors print to stderr and exit non-zero here, unlike the hook path which always
exits 0 -- a person typed this command and deserves to know it failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import aggregate as aggregate_mod
from . import worker
from .digest.render import render
from .extract.delta import Delta, build_delta
from .output import locate
from .transcript import claude_code

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="session_forensics",
        description="session-forensics: a running decision digest for coding sessions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    digest = sub.add_parser("digest", help="Build (or preview) a session digest from a transcript.")
    digest.add_argument("transcript", help="Path to a Claude Code transcript (.jsonl).")
    digest.add_argument(
        "--dry-run", action="store_true",
        help="Print the Delta that would be sent to a provider. Calls no provider, writes no digest.",
    )
    digest.add_argument(
        "--checkpoint-event", type=int, default=0, metavar="N",
        help="Resume from this event index (advanced; default 0 = from the start of the transcript).",
    )
    digest.add_argument(
        "--checkpoint-line", type=int, default=0, metavar="N",
        help="Resume from this transcript line (advanced; default 0 = from the start of the transcript).",
    )
    digest.add_argument(
        "--session-id", default=None,
        help="Defaults to the transcript's filename stem, matching Claude Code's own naming.",
    )
    digest.add_argument(
        "--cwd", default=None,
        help="Working directory to classify touched files against. Defaults to the "
             "transcript's own recorded cwd, when present.",
    )
    digest.add_argument(
        "--chunks", type=int, default=10, metavar="N",
        help="Replay the transcript as N bounded updates rather than one call covering "
             "everything -- the shape a real session actually produces (default 10).",
    )
    digest.add_argument(
        "--call-delay", type=float, default=4.0, metavar="SECONDS",
        help="Pause between real provider calls (default 4s) -- a real session spaces "
             "calls out naturally by however long the user takes between turns; this "
             "replay does not, and firing several in a tight loop can trip a per-minute "
             "rate limit that normal usage never would. 0 disables it.",
    )
    digest.set_defaults(func=_cmd_digest)

    aggregate = sub.add_parser(
        "aggregate", help="Merge every digest in a project into one chronological decision log.",
    )
    aggregate.add_argument(
        "--out", default=None, metavar="PATH",
        help="Write the merged document here. Defaults to stdout.",
    )
    aggregate.add_argument(
        "--cwd", default=None,
        help="Project directory to resolve .decisions/ from. Defaults to the current directory.",
    )
    aggregate.set_defaults(func=_cmd_aggregate)

    return parser


def _pin_utf8() -> None:
    """A Windows console defaults to cp1252 and raises on an arrow or an em dash.

    spec.md pins UTF-8 explicitly on every file, stream and request body; this is
    the stream half of that for the one entry point that writes to a real console.
    ``reconfigure`` is a no-op failure mode (AttributeError) on a stream that has
    already been replaced by something else -- caught rather than raised, since a
    person's terminal encoding is not something this tool can fail over.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _pin_utf8()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"session-forensics: error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # a person typed this command; they deserve a real error
        print(f"session-forensics: error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _cmd_digest(args: argparse.Namespace) -> int:
    if args.dry_run:
        delta = build_delta(
            args.transcript,
            checkpoint_event=args.checkpoint_event,
            checkpoint_line=args.checkpoint_line,
        )
        print(render_dry_run(delta))
        return 0

    session_id = args.session_id or Path(args.transcript).stem
    cwd = args.cwd or claude_code.parse(args.transcript).cwd
    # Deliberately stdout, not stderr, for this note -- see the comment on
    # _pin_utf8 below. PowerShell's native-command handling (version- and
    # profile-dependent: $PSNativeCommandUseErrorActionPreference) can promote
    # *any* stderr write from a native command into a formatted error record,
    # discarding the rest of the command's output when streams are redirected
    # with `*>`. Measured directly: an identical command produced a clean
    # digest in one PowerShell session and only a NativeCommandError in
    # another. stderr is reserved for genuine failures (see main()'s handlers
    # below); everything else -- including this note -- goes to stdout.
    print(
        f"session-forensics: replaying {args.transcript} as ~{args.chunks} bounded "
        f"updates (session {session_id}). This calls a real provider if a key is "
        f"configured, and does not write to .decisions/ yet -- Phase 4.\n",
    )
    digest = worker.run_over_transcript(
        args.transcript, session_id=session_id, cwd=cwd, chunks=args.chunks,
        call_delay_seconds=args.call_delay,
    )
    print(render(digest))
    return 0


def _cmd_aggregate(args: argparse.Namespace) -> int:
    cwd = args.cwd or str(Path.cwd())
    decisions_dir = locate.decisions_dir(cwd)
    entries = aggregate_mod.aggregate(decisions_dir)
    rendered = aggregate_mod.render_aggregate(entries)

    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0


def render_dry_run(delta: Delta) -> str:
    """Human-readable dump of a `Delta` -- everything that would leave the machine.

    Only human/assistant text and mechanical facts can appear here: `Delta.turns`
    already excludes reasoning, tool payloads and injected content structurally
    (`extract/delta.py`), not by a filter applied at print time.
    """
    out: list[str] = []
    out.append(f"=== Delta: event range {delta.range}, next checkpoint at transcript line {delta.checkpoint_line} ===")
    out.append("")
    out.append(f"-- turns ({len(delta.turns)}) --")
    for turn in delta.turns:
        tag = " [authorship inferred, no transcript field]" if turn.authorship_inferred else ""
        out.append(f"  [{turn.index}] {turn.role}{tag}: {turn.text}")

    out.append("")
    out.append(f"-- candidates ({len(delta.candidates)}) --")
    for candidate in delta.candidates:
        out.append(f"  [{candidate.signal}/{candidate.tier}] {candidate.title}")
        for ev in candidate.evidence:
            out.append(f"      ({ev.index}, {ev.kind}) {ev.detail}")

    f = delta.facts
    out.append("")
    out.append("-- facts --")
    out.append(f"  tools: {dict(f.tools)}")
    out.append(f"  files written: {dict(f.files_written)}")
    out.append(f"  files edited: {dict(f.files_edited)}")
    out.append(f"  files read: {dict(f.files_read)}")
    out.append(f"  tool failures: {f.tool_failures} / {f.tool_results}")
    out.append(f"  human messages: {f.human_messages} ({f.human_chars} chars, {f.human_inferred} authorship-inferred)")
    out.append(f"  assistant blocks: {f.assistant_blocks}, reasoning blocks: {f.reasoning_blocks} (never quoted)")
    if f.injected:
        out.append(f"  injected, not quotable: {dict(f.injected)}")

    if delta.compactions:
        out.append("")
        out.append(f"-- compactions in this delta ({len(delta.compactions)}) --")
        for index, dropped, pre, trigger in delta.compactions:
            out.append(f"  [{index}] trigger={trigger} cumulative_dropped_tokens={dropped} pre_tokens={pre}")

    if delta.unparseable:
        out.append("")
        out.append(f"-- {delta.unparseable} unparseable line(s) skipped in this delta --")

    out.append("")
    out.append(f"-- existing entry titles supplied to the model ({len(delta.existing_titles)}) --")
    for title in delta.existing_titles:
        out.append(f"  - {title}")

    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
