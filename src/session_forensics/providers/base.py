"""Provider abstraction: ``summarise(prompt, model=...) -> Completion``.

Every adapter (`gemini.py`, `openrouter.py`, `fake.py`) normalises to the same
`Completion` shape regardless of its own request/response format. Nothing
outside `providers/` knows a request shape -- `worker.py` and `digest/prompt.py`
call `summarise` and see only this interface (plan.md § Architecture).

Errors are typed so a caller can decide whether to fall back without knowing
*why* a specific provider failed: `retryable` is a property of the error class,
not a string match against a status code at the call site. Only three
conditions are retryable -- rate limit, quota exhaustion, server error -- per
spec.md's failover requirement. Everything else (malformed response, auth
failure, network/timeout failure) is terminal: the same request would fail
identically through the other provider, so a fallback attempt would only double
the latency of an update that was always going to fail.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Completion",
    "ProviderError",
    "RateLimited",
    "QuotaExhausted",
    "ServerError",
    "TerminalError",
    "MalformedResponse",
    "AuthError",
    "NetworkError",
]


@dataclass(frozen=True)
class Completion:
    """A provider's normalised response.

    ``tokens_in``/``tokens_out`` are real counts read from the provider's own
    response, never estimated -- spec.md's acceptance criteria require the
    digest footer to report measured usage, and an estimate silently violates
    that the moment a provider changes its tokenizer.
    """

    text: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str


class ProviderError(Exception):
    """Base for every provider failure.

    ``retryable`` decides whether `worker.py` attempts the fallback provider
    once (spec.md: failover only on conditions the other provider might
    survive). Defaults to ``False`` so a new error class is terminal unless it
    deliberately opts in.
    """

    retryable = False

    def __init__(self, message: str, *, provider: str):
        super().__init__(message)
        self.provider = provider


class RateLimited(ProviderError):
    """HTTP 429 / rate-limit response. Retryable."""

    retryable = True


class QuotaExhausted(ProviderError):
    """Daily or billing quota exhausted. Retryable -- the other provider has
    its own, independent quota.
    """

    retryable = True


class ServerError(ProviderError):
    """5xx from the provider. Retryable."""

    retryable = True


class TerminalError(ProviderError):
    """A condition the other provider would fail identically on. Never
    retried, never failed over -- retrying only doubles the latency of an
    update that was always going to fail.
    """

    retryable = False


class MalformedResponse(TerminalError):
    """Response body did not parse, or did not match the expected shape."""


class AuthError(TerminalError):
    """401/403 -- a bad or missing key. A local configuration problem, not
    something the other provider (with its own, different key) resolves.
    """


class NetworkError(TerminalError):
    """Timeout, connection refused, DNS failure. Not one of spec.md's three
    named retryable conditions -- if the network itself is the problem, the
    other provider is reachable over the same network and fails the same way.
    """
