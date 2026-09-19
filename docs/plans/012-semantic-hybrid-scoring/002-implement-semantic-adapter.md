# Task 012.002: Implement the Initial Semantic Adapter

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P2 |
| Depends on | 012.001 Define the semantic provider contract and configuration |
| PR | — |

## Objective

Call the selected provider through one narrow external boundary and normalize a
validated structured response without leaking SDK objects into domain code.

## Context and inputs

Semantic output is untrusted external data. Validation errors are deterministic
for a given response and must never be hidden by invented defaults or unbounded
retries.

## Expected changes

- Implement the selected provider call inside `adapters/scoring.py` or the
  repository's nearest equivalent.
- Build a versioned prompt/request from the task 001 project-owned input.
- Validate required dimensions, finite ranges, confidence, reason, and response
  shape before normalization.
- Classify timeout/rate-limit/transient failures separately from authentication,
  configuration, and malformed-response failures.
- Apply a small bounded retry policy only to documented retryable failures.
- Add hermetic contract fixtures for valid, incomplete, malformed, and
  out-of-range responses.

## Acceptance criteria

- Only the adapter imports provider-specific types or SDK modules.
- Valid responses normalize to project-owned semantic judgments with exact
  provider/model/prompt provenance.
- Missing dimensions, non-finite numbers, invalid ranges, and invalid JSON are
  rejected as provider failures rather than repaired silently.
- Retry count is bounded and deterministic validation failures are not retried.
- Exceptions preserve their cause while messages/logs omit secrets and avoid
  logging complete candidate/context text.
- Unit tests require no network or real credentials.

## Tests and validation

```bash
pytest tests/unit -k "semantic and adapter"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- SDK-specific response changes should affect only adapter tests and
  normalization.
- Live provider tests, if useful, must be opt-in integration tests and must not
  gate the hermetic suite.
