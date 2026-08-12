"""Gemini adapter -- Google generative-language REST, over urllib only.

https://ai.google.dev/api/rest -- generateContent. No SDK: a POST with the key
in the query string and a JSON body, normalised to `Completion`. Primary
provider (spec.md: daily allowance comfortably exceeds the 15-30 call workload).
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

NAME = "gemini"
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

#: Low temperature: this is factual extraction from a transcript, not creative
#: writing, and consistency matters more than variety across many small calls
#: in the same session (plan.md doesn't pin a value; recorded here and in
#: plan.md's Tech Stack table since it is a real, if minor, tuning decision).
_TEMPERATURE = 0.2


def has_key() -> bool:
    """Whether a call is even worth attempting. `worker.py` checks this on the
    *fallback* before trying it after a retryable primary failure -- spec.md:
    a missing fallback key must never be treated as an error, which requires
    not attempting it in the first place rather than attempting and catching.
    """
    return config.gemini_api_key() is not None


def summarise(prompt: str, *, model: str) -> Completion:
    """Raises an appropriate `ProviderError` subclass; never returns partial data."""
    api_key = config.gemini_api_key()
    if not api_key:
        raise AuthError("GEMINI_API_KEY is not set", provider=NAME)

    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": _TEMPERATURE,
        },
    }).encode("utf-8")

    url = f"{_ENDPOINT.format(model=model)}?key={api_key}"
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    try:
        with urllib.request.urlopen(request, timeout=config.PROVIDER_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise _map_http_error(exc) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        raise NetworkError(f"network failure calling Gemini: {exc}", provider=NAME) from exc

    return _parse(raw, model)


def _map_http_error(exc: urllib.error.HTTPError) -> ProviderError:
    message, status = str(exc.reason), ""
    try:
        body = json.loads(exc.read().decode("utf-8"))
        error = (body or {}).get("error") or {}
        message = str(error.get("message") or message)
        status = str(error.get("status") or "")
    except Exception:
        pass  # fall through with the HTTP reason phrase; a bad error body is not fatal here

    code = exc.code
    if code == 429:
        if status == "RESOURCE_EXHAUSTED" and "quota" in message.lower():
            return QuotaExhausted(message, provider=NAME)
        return RateLimited(message, provider=NAME)
    if code in (401, 403):
        return AuthError(message, provider=NAME)
    if code >= 500:
        return ServerError(message, provider=NAME)
    return MalformedResponse(f"HTTP {code}: {message}", provider=NAME)


def _parse(raw: str, model: str) -> Completion:
    try:
        data = json.loads(raw)
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount", 0))
        tokens_out = int(usage.get("candidatesTokenCount", 0))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MalformedResponse(f"unexpected Gemini response shape: {exc}", provider=NAME) from exc

    if not text:
        raise MalformedResponse("Gemini returned no text", provider=NAME)

    return Completion(text=text, tokens_in=tokens_in, tokens_out=tokens_out, model=model, provider=NAME)
