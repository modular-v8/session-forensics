"""Environment-driven configuration.

Every value is read fresh from ``os.environ`` on each call, never cached at import
time. Hook invocations are separate short-lived processes; a module-level constant
computed once at import would go stale in exactly the case that matters -- a key
added, a threshold tuned, between one invocation and the next.

Environment variables only -- a configuration file is out of scope for v1
(spec.md, out of scope).
"""

from __future__ import annotations

import os

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
