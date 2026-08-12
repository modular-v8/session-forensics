"""Fail-closed, span-level redaction.

Every string entering a payload sent to a model provider passes through here
first -- before the payload is constructed, not as a filter applied to it
afterward (spec.md: "nothing is transmitted before redaction"). On any internal
failure this raises rather than returning a partially-cleaned string: a caller
holding a return value from this module must be able to trust it completely,
because there is no second check downstream.

Six pattern classes, matching spec.md exactly: provider key shapes, JWTs, PEM
blocks, `KEY=value` env lines, `scheme://user:pass@host` URLs, and the generic
`(api_key|secret|token|password|bearer): value` form. Each match is replaced
span-wise with `[REDACTED:kind]`, leaving surrounding context intact -- this
redacts the credential, not the sentence describing it.

This catches key-*shaped* strings. It does not and cannot catch a sentence that
describes a secret in prose without reproducing its shape -- that residual risk
is documented in spec.md § risks and is why the opt-out marker exists as a
separate, stronger control.
"""

from __future__ import annotations

import re

__all__ = ["redact", "RedactionError"]


class RedactionError(Exception):
    """Raised when a string cannot be confidently redacted.

    Callers must not fall back to the original text on this -- there is no
    second check downstream of this module.
    """


# ---------------------------------------------------------------------------
# Pattern classes
# ---------------------------------------------------------------------------

# 1. PEM blocks. The whole block is replaced, markers included: even knowing
#    "an RSA key was here" is less useful than it is risky to parse further.
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]*?-----END [A-Z0-9 ]+-----")

# 2. JWTs: header.payload.signature, base64url. Anchored on the near-universal
#    `eyJ` header prefix (base64 of `{"`) to keep false positives negligible.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")

# 3. Known provider key shapes. Each prefix is distinctive enough that a false
#    positive on ordinary prose is effectively impossible.
_PROVIDER_KEYS = re.compile(
    r"\b("
    r"sk-ant-[A-Za-z0-9_-]{20,}"       # Anthropic
    r"|sk-or-v1-[A-Za-z0-9]{20,}"      # OpenRouter
    r"|sk-proj-[A-Za-z0-9_-]{20,}"     # OpenAI project key
    r"|sk-[A-Za-z0-9]{20,}"            # OpenAI legacy / other sk- vendors
    r"|AIza[A-Za-z0-9_-]{35}"          # Google / Gemini
    r"|gh[pousr]_[A-Za-z0-9]{36,}"     # GitHub (personal/oauth/user-to-server/refresh)
    r"|AKIA[A-Z0-9]{16}"               # AWS access key id
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"   # Slack
    r")\b"
)

# 4. scheme://user:pass@host -- redact only the credential span so the scheme
#    and host, which are not secret, survive as context.
_URL_CREDENTIALS = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^\s/@:]+):([^\s/@]+)(@)")

# 5. KEY=value env-file lines, keyed on a secret-shaped variable name.
_ENV_LINE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL)[A-Za-z0-9_]*)"
    r"(\s*=\s*)"
    r"(?!\[REDACTED:)([^\s]+)",
    re.IGNORECASE,
)

# 6. The generic "label: value" / "label=value" form, plus bare "Bearer <token>"
#    which carries no punctuation between label and value.
_BEARER = re.compile(r"\bBearer\s+(?!\[REDACTED:)([A-Za-z0-9\-_.~+/]{8,}=*)", re.IGNORECASE)
_LABELLED = re.compile(
    r'\b(api[_-]?key|secret|access[_-]?token|refresh[_-]?token|token|password|passwd|pwd)'
    r'("?\s*[:=]\s*"?)'
    r"""(?!\[REDACTED:)([^\s,;"'\)\]\}]+)""",
    re.IGNORECASE,
)

_PASSES = (
    (_PEM, lambda m: "[REDACTED:pem]"),
    (_JWT, lambda m: "[REDACTED:jwt]"),
    (_PROVIDER_KEYS, lambda m: "[REDACTED:provider_key]"),
    (_URL_CREDENTIALS, lambda m: f"{m.group(1)}[REDACTED:url_credentials]{m.group(4)}"),
    (_ENV_LINE, lambda m: f"{m.group(1)}{m.group(2)}[REDACTED:env]"),
    (_BEARER, lambda m: "Bearer [REDACTED:token]"),
    (_LABELLED, lambda m: f"{m.group(1)}{m.group(2)}[REDACTED:secret]"),
)


def redact(text: str) -> str:
    """Return `text` with every recognised secret-shaped span replaced.

    Raises `RedactionError` on anything that prevents a confident result. A
    normal return is a guarantee, not a best-effort cleanup.
    """
    if not isinstance(text, str):
        raise RedactionError(f"redact() requires str, got {type(text).__name__}")
    if text == "":
        return text
    try:
        out = text
        for pattern, replacement in _PASSES:
            out = pattern.sub(replacement, out)
        return out
    except RedactionError:
        raise
    except Exception as exc:  # defensive: patterns are static and pre-compiled
        raise RedactionError(f"redaction failed: {exc}") from exc
