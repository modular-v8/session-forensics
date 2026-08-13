"""Environment-driven configuration.

Every value is read fresh from ``os.environ`` on each call, never cached at import
time. Hook invocations are separate short-lived processes; a module-level constant
computed once at import would go stale in exactly the case that matters -- a key
added, a threshold tuned, between one invocation and the next.

Environment variables, optionally seeded from a `.env` file at the repo root
(`load_dotenv`, tasks.md T4.12). v1 originally scoped this out (spec.md) in
favour of a real, persistent OS environment variable -- reversed after direct
user feedback: `setx` plus a full Claude Code restart is real, reported setup
friction for a tool whose whole point is minimal ceremony, and most developers
already have a project `.env` from other tooling. Implemented as a small,
dependency-free parser rather than adopting `python-dotenv`, keeping this
project's "standard library only" property intact.
"""

from __future__ import annotations

import os
from pathlib import Path

from .repo import repo_root

__all__ = [
    "gemini_api_key",
    "openrouter_api_key",
    "model_primary",
    "model_fallback",
    "turn_threshold",
    "char_threshold",
    "call_cap",
    "out_dir",
    "log_level",
    "section_caps",
    "word_cap",
    "load_dotenv",
    "LOCK_STALE_SECONDS",
    "PROVIDER_TIMEOUT_SECONDS",
]

# Defaults. Each is a guess flagged in plan.md except where a task measured it;
# see docs/signals.md and tasks.md T4.10 for the threshold measurement record.
#
# Model defaults, corrected during T3.9: the first choices here (gemini-2.5-flash,
# openai/gpt-4o-mini) were reasonable as of this tool's training-cutoff knowledge
# but had already been superseded by the time of real-world testing -- the Gemini
# name specifically caused every real call to hang until timeout rather than fail
# cleanly. `gemini-flash-latest` is Google's own "hot-swapped with every release"
# alias (confirmed against ai.google.dev's model docs), chosen specifically so
# this default does not go stale the same way again. `openai/gpt-5-mini` was
# confirmed live via OpenRouter's own /api/v1/models endpoint at the time of
# writing. Both remain fully overridable via SF_MODEL_PRIMARY/SF_MODEL_FALLBACK.
_DEFAULT_MODEL_PRIMARY = "gemini-flash-latest"
_DEFAULT_MODEL_FALLBACK = "openai/gpt-5-mini"
_DEFAULT_TURN_THRESHOLD = 4
_DEFAULT_CHAR_THRESHOLD = 6000
_DEFAULT_CALL_CAP = 25
_DEFAULT_OUT_DIR = ".decisions"
_DEFAULT_LOG_LEVEL = "INFO"

# Not environment-configurable -- spec.md lists the env surface explicitly and
# these are not on it. Fixed by plan.md § Tech Stack; enforced in code regardless
# of what a model returns.
_SECTION_CAPS = {"decided": 12, "rejected": 8, "open": 5}
_WORD_CAP = 25

#: A worker lock older than this is taken over rather than honoured, so a crashed
#: worker cannot disable summarising for a session permanently (tasks.md T4.4).
LOCK_STALE_SECONDS = 600

#: plan.md § Tech Stack: "20s connect+read, no in-request retries."
PROVIDER_TIMEOUT_SECONDS = 20


def _int_env(name: str, default: int) -> int:
    """A malformed integer falls back to its default rather than raising.

    A hook must never fail because someone typo'd a threshold in settings.json.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or None


def openrouter_api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY") or None


def model_primary() -> str:
    return os.environ.get("SF_MODEL_PRIMARY") or _DEFAULT_MODEL_PRIMARY


def model_fallback() -> str:
    return os.environ.get("SF_MODEL_FALLBACK") or _DEFAULT_MODEL_FALLBACK


def turn_threshold() -> int:
    return _int_env("SF_TURN_THRESHOLD", _DEFAULT_TURN_THRESHOLD)


def char_threshold() -> int:
    return _int_env("SF_CHAR_THRESHOLD", _DEFAULT_CHAR_THRESHOLD)


def call_cap() -> int:
    return _int_env("SF_CALL_CAP", _DEFAULT_CALL_CAP)


def out_dir() -> str:
    return os.environ.get("SF_OUT_DIR") or _DEFAULT_OUT_DIR


def log_level() -> str:
    return (os.environ.get("SF_LOG_LEVEL") or _DEFAULT_LOG_LEVEL).strip().upper()


def section_caps() -> dict[str, int]:
    """``{section: max_entries}``. A copy -- callers must not mutate the default."""
    return dict(_SECTION_CAPS)


def word_cap() -> int:
    return _WORD_CAP


def load_dotenv(cwd: str | Path) -> str | None:
    """Best-effort: if `<repo_root>/.env` exists, its ``KEY=value`` pairs are
    merged into ``os.environ`` for any key not already set there. A real
    environment variable always wins -- standard dotenv precedence, and it
    means the original setx-based path keeps working completely unchanged
    for anyone already using it.

    Returns a warning string if `.env` exists but does not look covered by
    the repo's own `.gitignore` -- never raises, never blocks; the caller
    logs it if present. This is a best-effort textual check (an exact-line
    match on common patterns), not a full `.gitignore` engine -- good enough
    to catch the one mistake that actually matters here (a key about to be
    committed), not a general-purpose ignore resolver.

    Call once, early, before any `gemini_api_key`/`openrouter_api_key`
    lookup -- everything downstream still just reads `os.environ` fresh, so
    this is the only place `.env` is ever read from.
    """
    dotenv_path = repo_root(cwd) / ".env"
    if not dotenv_path.is_file():
        return None

    for key, value in _parse_dotenv(dotenv_path).items():
        os.environ.setdefault(key, value)

    return _warn_if_unprotected(dotenv_path)


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Minimal ``KEY=value`` parsing -- no interpolation, no multi-line
    values. Blank lines and ``#``-prefixed comments are skipped; an optional
    leading ``export `` and surrounding matched quotes on the value are
    stripped, covering the two conventions real `.env` files use in practice
    without pulling in a dependency for it.
    """
    pairs: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return pairs
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            pairs[key] = value
    return pairs


_DOTENV_IGNORE_PATTERNS = {".env", "/.env", ".env*", "/.env*", "*.env"}


def _warn_if_unprotected(dotenv_path: Path) -> str | None:
    gitignore_path = dotenv_path.parent / ".gitignore"
    try:
        lines = {ln.strip() for ln in gitignore_path.read_text(encoding="utf-8").splitlines()}
    except OSError:
        lines = set()
    if lines & _DOTENV_IGNORE_PATTERNS:
        return None
    return (
        f"{dotenv_path} does not appear to be covered by {gitignore_path} -- "
        "add a line for it, or any key(s) in it risk being committed"
    )
