"""Stop / SessionEnd / PreCompact hook entry point.

Reads stdin, decides whether enough has changed to be worth an update, and
either spawns a detached worker or exits -- nothing else. This runs after
every assistant turn on a path the user is waiting on, so it must be
impossible for a parser bug, a slow disk, or a network hiccup anywhere in the
real pipeline to touch it. Imports only `json`, `os`, `sys`, `subprocess`,
`pathlib`, `config` plus `threshold` (added at T4.6 specifically to keep the
threshold check out of this file without pulling in `output/`) -- nothing from
`transcript/`, `extract/`, `providers/` or `output/` (plan.md's import
allowlist for this file).

Exits 0 unconditionally, in every circumstance -- spec.md: a non-zero hook
exit can make Claude Code report an error or stall the user's next turn, and
a digest tool must never break a session. There is deliberately nowhere for
this module to log a problem to (`log.py` is not in its import list either):
if something here is wrong, the spawned worker's own diagnostics are where it
surfaces, not here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import threshold

__all__ = ["main"]

#: spec.md § event-driven: these two always update regardless of threshold.
_ALWAYS_TRIGGER_EVENTS = frozenset({"SessionEnd", "PreCompact"})


def main() -> int:
    try:
        _run()
    except Exception:
        pass  # nowhere safe to log from here; see module docstring
    return 0


def _run() -> None:
    payload = json.load(sys.stdin)
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    cwd = payload.get("cwd")
    hook_event_name = payload.get("hook_event_name")

    if not session_id or not transcript_path or not cwd:
        return  # malformed payload -- nothing safe to do with it

    if hook_event_name in _ALWAYS_TRIGGER_EVENTS or threshold.should_trigger(
        session_id=session_id, transcript_path=transcript_path, cwd=cwd
    ):
        _spawn_worker(session_id=session_id, transcript_path=transcript_path, cwd=cwd)


def _spawn_worker(*, session_id: str, transcript_path: str, cwd: str) -> None:
    """`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, stdio to `DEVNULL`, no
    shell (spec.md § constraints). Survives this process's exit; see tasks.md
    T4.7 for the direct confirmation that it does.

    `-m session_forensics.worker` needs the package findable on `PYTHONPATH`.
    This process's own `sys.path` does not propagate to a child process --
    only environment variables do -- so `PYTHONPATH` is set explicitly here
    from this file's own known location (`.../src/session_forensics/`, two
    parents up is `src/`) rather than assumed inherited. This makes the spawn
    correct regardless of how *this* process itself was launched -- plugin
    hook, manual settings.json entry, or a bootstrap script that only set
    `sys.path` in-process (T4.8's `hooks/run_hookrunner.py`).
    """
    src_dir = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir if not env.get("PYTHONPATH") else os.pathsep.join([src_dir, env["PYTHONPATH"]])

    subprocess.Popen(
        [sys.executable, "-m", "session_forensics.worker", session_id, transcript_path, cwd],
        cwd=cwd,
        env=env,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
