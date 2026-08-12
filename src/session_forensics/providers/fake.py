"""A canned-response provider. No network, no key, no cost.

Every downstream task in Phase 3 -- merge, caps, rendering, failover -- is
testable through this with nothing else running. CI uses it exclusively: CI
must never make a paid call (tasks.md T3.2, T6.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .base import Completion, ProviderError

__all__ = ["FakeProvider", "entries_completion"]


@dataclass
class FakeProvider:
    """Configurable stand-in for a real provider.

    Construct with either `response` (a canned `Completion` to return) or
    `error` (an exception instance, or a `ProviderError` subclass to
    instantiate on each call) -- not both. Every call is recorded in `.calls`
    so a test can assert how many times `summarise` ran and what it was asked.
    """

    name: str = "fake"
    response: Completion | None = None
    error: ProviderError | type[ProviderError] | None = None
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.response is not None and self.error is not None:
            raise ValueError("FakeProvider takes a response or an error, not both")

    def summarise(self, prompt: str, *, model: str) -> Completion:
        self.calls.append(prompt)
        if self.error is not None:
            if isinstance(self.error, type):
                raise self.error("forced failure", provider=self.name)
            raise self.error
        if self.response is not None:
            return self.response
        return Completion(text="[]", tokens_in=len(prompt.split()), tokens_out=0,
                           model=model, provider=self.name)

    @property
    def call_count(self) -> int:
        return len(self.calls)


def entries_completion(
    entries: list[dict],
    *,
    provider: str = "fake",
    model: str = "fake-model",
    tokens_in: int = 100,
) -> Completion:
    """A `Completion` whose text is a strict JSON array of entries -- the exact
    shape `digest/prompt.py` expects back from a real provider. Use this to
    build the `response` a `FakeProvider` returns.
    """
    text = json.dumps(entries)
    return Completion(text=text, tokens_in=tokens_in, tokens_out=max(1, len(text.split())),
                       model=model, provider=provider)
