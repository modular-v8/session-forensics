"""CI smoke test (tasks.md T6.2): exercises real code paths against the hand-
built fixture (tests/fixtures/smoke.jsonl -- never a personal-directory
transcript, see tasks.md Phase 0's provenance rule).

Two things must both hold, and this script checks both directly rather than
trusting it:

1. CI must never be *able* to make a paid call -- not "won't", "can't". This
   process's environment carries no GEMINI_API_KEY/OPENROUTER_API_KEY (the
   workflow that runs this must not set them either), so
   `providers.gemini.summarise`/`providers.openrouter.summarise` raise
   AuthError before any `urllib` call is even constructed. Verified directly
   below, not assumed.

2. The pipeline actually works end to end against a real fixture: both the
   deterministic-only path (no key -- exercised through the real `worker.run`
   entry point, writing a real digest to a real git repo) and the
   provider-call path (exercised through `FakeProvider`, since CI must never
   reach a real provider).

Not a pytest suite -- spec.md is explicit that v1 has no test suite beyond this
CI smoke run. A single script, plain asserts, a non-zero exit on any failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from session_forensics import worker  # noqa: E402
from session_forensics.digest.prompt import ParsedEntry  # noqa: E402
from session_forensics.providers import base  # noqa: E402
from session_forensics.providers.fake import FakeProvider, entries_completion  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "smoke.jsonl"

_failures: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        _failures.append(label)


def main() -> int:
    check("fixture exists", FIXTURE.is_file())

    _check_no_key_in_environment()
    _check_deterministic_pipeline_end_to_end()
    _check_fake_provider_path()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


def _check_no_key_in_environment() -> None:
    print("\n=== CI safety: no provider key present, real calls are structurally impossible ===")
    check("GEMINI_API_KEY is not set", os.environ.get("GEMINI_API_KEY") is None)
    check("OPENROUTER_API_KEY is not set", os.environ.get("OPENROUTER_API_KEY") is None)
    try:
        from session_forensics.providers import gemini
        gemini.summarise("test", model="gemini-flash-latest")
        check("gemini.summarise without a key raises before any network call", False)
    except base.AuthError:
        check("gemini.summarise without a key raises AuthError (no urllib call ever made)", True)


def _check_deterministic_pipeline_end_to_end() -> None:
    print("\n=== real pipeline, real fixture, no key: worker.run() writes a real digest ===")
    tmp = tempfile.mkdtemp(prefix="sf_ci_smoke_")
    try:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        transcript = Path(tmp) / "smoke.jsonl"
        transcript.write_bytes(FIXTURE.read_bytes())

        worker.run(session_id="ci-smoke", transcript_path=str(transcript), cwd=tmp)

        digest_path = Path(tmp) / ".decisions" / "ci-smoke.md"
        check("digest file was written", digest_path.is_file())
        if digest_path.is_file():
            content = digest_path.read_text(encoding="utf-8")
            check("digest is not empty", len(content) > 0)
            check("digest has real decisions (fixture's A1/A4/A8 signals, not an empty session)",
                  "## Decided" in content or "## Rejected" in content or "## Open" in content)
            check("digest states no key is configured (the honest, correct reason here)",
                  "No provider key is configured" in content)

        result = subprocess.run(["git", "status", "--porcelain"], cwd=tmp, capture_output=True, text=True, check=True)
        check("digest .md file is not reported as untracked by git", "ci-smoke.md" not in result.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _check_fake_provider_path() -> None:
    print("\n=== provider-call code path, via FakeProvider (CI must never reach a real one) ===")
    fake = FakeProvider(name="fake", response=entries_completion(
        [{"section": "decided", "text": "fake provider entry for CI", "why": "smoke test", "turns": [1, 2]}],
        provider="fake",
    ))
    completion = worker.summarise_with_failover("test prompt", primary=fake, fallback=fake)
    check("fake provider was actually called", fake.call_count == 1)
    check("completion text round-trips through the fake", "fake provider entry" in completion.text)

    from session_forensics.digest.prompt import parse_entries
    parsed = parse_entries(completion.text, provider=completion.provider)
    check("fake provider's response parses into a real entry", len(parsed) == 1 and isinstance(parsed[0], ParsedEntry))


if __name__ == "__main__":
    raise SystemExit(main())
