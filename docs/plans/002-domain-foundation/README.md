# Package 002: Domain Foundation

| Field | Value |
| --- | --- |
| Milestone | M0 — Foundation |
| Status | in-progress |
| Priority | P0 |
| Depends on | 001 Project bootstrap |
| Unlocks | 003 CLI and pipeline foundation; 004 Local source and media |

## Objective and expected outcome

Define the typed, provider-independent contracts needed to validate a run,
describe a local source and its media, and represent a normalized transcript.
Completion gives downstream packages stable value objects and actionable project
errors without pulling external libraries into domain code.

## Context

Acquisition, probing, transcription, CLI handling, and artifact persistence all
need shared data. The architecture assigns those values to `models.py`, run
validation to `config.py`, and the small exception hierarchy to `errors.py`.

## Included scope

- the documented `MulticutsError` hierarchy;
- `RunConfig` covering the documented MVP CLI inputs and early semantic
  validation;
- `AcquiredSource`, `MediaInfo`, `Word`, `TranscriptSegment`, and `Transcript`;
- enums only for closed sets that benefit from validation, such as aspect-ratio
  mode;
- serialization-friendly, typed fields required through transcription;
- unit tests for model invariants and configuration validation.

## Out of scope

- candidate, score, selected-clip, render, and manifest models;
- provider response models or raw provider dictionaries;
- filesystem persistence and cache keys;
- acquisition, probing, transcription, or CLI parsing;
- a configuration framework, DI container, or general validation layer.

## Requirements and established decisions

- [PRD: CLI options](../../prd.md#91-cli)
- [PRD: conceptual data model](../../prd.md#10-conceptual-data-model)
- [Architecture: module responsibilities](../../architecture.md#6-module-responsibilities)
- [Conventions: data models](../../conventions.md#9-data-models)
- [Conventions: configuration](../../conventions.md#10-configuration)
- [Conventions: exceptions and errors](../../conventions.md#11-exceptions-and-errors)

## Likely components

- `src/multicuts/errors.py`
- `src/multicuts/models.py`
- `src/multicuts/config.py`
- `tests/unit/`

## Task index

| Task | Status | Depends on | Outcome |
| --- | --- | --- | --- |
| [001 Define error hierarchy](001-define-error-hierarchy.md) | completed | Package 001 | Stable project failure categories |
| [002 Define core models](002-define-core-models.md) | in-progress | Package 001 | Provider-independent values through transcription |
| [003 Define run configuration](003-define-run-configuration.md) | planned | 002 | Validated immutable run configuration |

## Completion criteria

- Shared/public fields are fully typed and valid on Python 3.10.
- No domain model stores a provider-owned object or broad untyped payload.
- Configuration rejects invalid clip counts, score ranges, duration ranges,
  aspect-ratio values, and invalid supplied template directories before any
  expensive work.
- Exceptions support the documented CLI failure categories and preserve chaining.
- Focused unit tests pass with no external tools or network.

## Risks, assumptions, and open questions

- Dataclasses are the planning assumption because the conventions prefer them;
  adding Pydantic is not justified by the current requirements.
- Defaults exist for minimum and maximum duration, but several other CLI defaults
  remain unspecified. Keep them explicit and reviewable rather than guessing
  platform-specific policy.
- Models should contain only fields consumed by packages 003–006. Later packages
  extend the model set when their requirements are implemented.
