"""Repository root, `.decisions/` resolution, and the write gate.

No digest is written until `.decisions/` exists and its `.gitignore` has been
written *and* read back with the expected content -- spec.md's write gate. A
digest committed to the repository would contain the user's own prompts, and
the measured corpus includes job applications and financial records
(docs/signals.md § 1). Failure here is a refusal, not a crash: the caller (T4.5)
logs it and exits 0 without writing anything.
"""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..repo import repo_root

__all__ = [
    "LocateError",
    "repo_root",
    "decisions_dir",
    "ensure_gitignore",
    "locate",
    "state_dir",
    "state_path",
    "lock_path",
    "digest_path",
]

_GITIGNORE_CONTENT = "*\n!.gitignore\n"


class LocateError(Exception):
    """The write gate refused. Caller must log the refusal and write nothing."""


# repo_root is defined in ..repo (T4.6: threshold.py needs it too, and cannot
# import output/ at all -- see hookrunner.py's import allowlist). Re-exported
# here so every existing caller of `locate.repo_root` keeps working unchanged.


def decisions_dir(cwd: str | Path) -> Path:
    """`<repo_root>/<SF_OUT_DIR>`, resolved but not created."""
    return repo_root(cwd) / config.out_dir()


def ensure_gitignore(out_dir: str | Path) -> Path:
    """Create `out_dir` and write+verify its `.gitignore` -- but only on a
    fresh setup, where `out_dir` does not exist yet.

    If `out_dir` already exists, its `.gitignore` must already be exactly
    correct; any deviation -- missing, wrong content, or unreadable -- refuses
    rather than silently rewriting it. This is a corrected reading of
    spec.md, not the original one: an earlier version of this function
    self-healed a missing/wrong `.gitignore` unconditionally, reasoned from
    "the tool owns this file, so fixing drift is fine." That directly
    contradicted spec.md's own acceptance criteria ("removing
    `.decisions/.gitignore` and re-running results in no digest being
    written") and tasks.md T4.1's acceptance line ("deleting *or* corrupting
    the `.gitignore` ... causes the write path to refuse"), caught during the
    T6.6 acceptance-criteria pass rather than at T4.1 itself.

    The distinction that reconciles both: "in a fresh git repo, the directory
    and its `.gitignore` are created" (spec.md) describes `out_dir` not
    existing yet -- creating it fresh is exactly the intended behaviour, not
    a refusal case. Once `out_dir` exists, presumably with digests already
    inside it, its safety marker disappearing or changing is not something to
    paper over -- it is refused, logged, and left for a human to notice.
    """
    out_dir = Path(out_dir)
    pre_existing = out_dir.is_dir()
    gitignore = out_dir / ".gitignore"

    if pre_existing:
        try:
            current = gitignore.read_text(encoding="utf-8") if gitignore.exists() else None
        except OSError as exc:
            raise LocateError(f"could not read {gitignore}: {exc}") from exc
        if current != _GITIGNORE_CONTENT:
            raise LocateError(
                f"{gitignore} is missing or does not match the expected content; "
                f"refusing to write into {out_dir} until it is restored"
            )
        return gitignore

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        gitignore.write_text(_GITIGNORE_CONTENT, encoding="utf-8")
        verified = gitignore.read_text(encoding="utf-8")
    except OSError as exc:
        raise LocateError(f"could not create/write/verify {gitignore}: {exc}") from exc

    if verified != _GITIGNORE_CONTENT:
        raise LocateError(f"{gitignore} does not contain the expected content after writing")

    return gitignore


def locate(cwd: str | Path) -> Path:
    """Resolve, create and verify `.decisions/` for the repository containing
    `cwd`. The single entry point worker.py calls; raises `LocateError` if the
    write gate refuses.
    """
    out_dir = decisions_dir(cwd)
    ensure_gitignore(out_dir)
    return out_dir


# Paths within an already-located `.decisions/`. `.state/` needs no `.gitignore`
# of its own: the parent's `*` pattern already covers it recursively.

def state_dir(decisions_dir: str | Path) -> Path:
    return Path(decisions_dir) / ".state"


def state_path(decisions_dir: str | Path, session_id: str) -> Path:
    return state_dir(decisions_dir) / f"{session_id}.json"


def lock_path(decisions_dir: str | Path, session_id: str) -> Path:
    return state_dir(decisions_dir) / f"{session_id}.lock"


def digest_path(decisions_dir: str | Path, session_id: str) -> Path:
    return Path(decisions_dir) / f"{session_id}.md"
