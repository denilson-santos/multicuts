# Task 002.001: Define the Error Hierarchy

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P0 |
| Depends on | Package 001 Project bootstrap |

## Objective

Provide the small project exception hierarchy required for adapter translation
and CLI exit-code mapping.

## Context and inputs

The architecture defines `MulticutsError` with configuration, acquisition,
media, transcription, scoring, rendering, and artifact categories. Callers need
these categories to report safe, actionable failures without knowing provider
exceptions.

## Expected changes

- Add `MulticutsError` as the project base exception.
- Add `ConfigurationError`, `AcquisitionError`, `MediaError`,
  `TranscriptionError`, `ScoringError`, `RenderingError`, and `ArtifactError`.
- Keep exceptions free of provider-specific payloads and behavior.
- Add concise public docstrings and tests for inheritance/chaining behavior.

## Suggested sequence

1. Implement only the documented classes in `errors.py`.
2. Verify every specific error derives from `MulticutsError`.
3. Demonstrate `raise ... from exc` preserves `__cause__` without exposing
   secrets in the public message.

## Acceptance criteria

- Callers can catch all expected failures as `MulticutsError` or a documented
  category.
- No new subtype is introduced without a distinct caller reaction.
- Exceptions do not perform logging, formatting, or process exit themselves.
- Unit tests verify inheritance and exception chaining.

## Tests and validation

```bash
pytest tests/unit -k error
ruff check src/multicuts/errors.py tests
pyright
```

## Risks and exclusions

- Error messages belong at the layer with operation/resource context, not in
  empty exception constructors.
- Do not encode CLI exit numbers in domain exceptions.
- Do not catch broad `Exception` in domain code as part of this task.
