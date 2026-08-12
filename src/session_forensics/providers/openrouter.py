"""OpenRouter adapter -- OpenAI-compatible chat completions, over urllib only.

https://openrouter.ai/docs/api-reference/chat-completion. No SDK: a POST with a
bearer token and a JSON body, normalised to `Completion`. Fallback provider
only -- one string away from many models when Gemini is unavailable, but its
daily allowance does not fit the 15-30 call workload (spec.md).
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from .. import config
from .base import (
    AuthError,
    Completion,
    MalformedResponse,
    NetworkError,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    ServerError,
)

__all__ = ["NAME", "summarise", "has_key"]

NAME = "openrouter"
_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_TEMPERATURE = 0.2  # see gemini.py -- factual extraction, not creative writing


def has_key() -> bool:
    """See gemini.has_key -- same reason, checked on whichever side is acting
    as the fallback."""
    return config.openrouter_api_key() is not None


def summarise(prompt: str, *, model: str) -> Completion:
    """Raises an appropriate `ProviderError` subclass; never returns partial data."""
    api_key = config.openrouter_api_key()
    if not api_key:
        raise AuthError("OPENROUTER_API_KEY is not set", provider=NAME)

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": _TEMPERATURE,
    }).encode("utf-8")

    request = urllib.request.Request(
        _ENDPOINT, data=body, method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=config.PROVIDER_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise _map_http_error(exc) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        raise NetworkError(f"network failure calling OpenRouter: {exc}", provider=NAME) from exc

    return _parse(raw, model)


def _map_http_error(exc: urllib.error.HTTPError) -> ProviderError:
    message = str(exc.reason)
    try:
        body = json.loads(exc.read().decode("utf-8"))
        message = str((body or {}).get("error", {}).get("message") or message)
    except Exception:
        pass  # fall through with the HTTP reason phrase; a bad error body is not fatal here

    code = exc.code
    if code == 429:
        return RateLimited(message, provider=NAME)
    if code == 402:
        return QuotaExhausted(message, provider=NAME)  # OpenRouter: out of credits
    if code in (401, 403):
        return AuthError(message, provider=NAME)
    if code >= 500:
        return ServerError(message, provider=NAME)
    return MalformedResponse(f"HTTP {code}: {message}", provider=NAME)


def _parse(raw: str, model: str) -> Completion:
    try:
        data = json.loads(raw)
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MalformedResponse(f"unexpected OpenRouter response shape: {exc}", provider=NAME) from exc

    if not text:
        raise MalformedResponse("OpenRouter returned no text", provider=NAME)

    return Completion(text=text, tokens_in=tokens_in, tokens_out=tokens_out, model=model, provider=NAME)
