# Task 015.002: Establish the Public `multisubs` Subtitle-Artifact Contract

| Field | Value |
| --- | --- |
| Status | blocked |
| Priority | P1 |
| Depends on | 015.001 Derive clip-local transcripts; a supported public `multisubs` release/API that builds subtitle artifacts from existing timed transcript data |
| PR | — |

## Objective

Verify and adapt a supported public `multisubs` contract that creates styled
subtitle artifacts for a target video from an existing `ClipTranscript`, with
no transcription step.

## Context and inputs

The documented installed baseline exposes transcription and ASS embedding but
not the public middle operation required by multicuts. Project rules explicitly
forbid importing private renderer/layout/template/animation modules.

## Expected changes

- Coordinate or consume a public `multisubs` API accepting existing timed cues,
  target video/geometry, template, optional template directory, and output path.
- Decide and document the minimum supported `multisubs` version once that API is
  released, without silently widening or narrowing compatibility.
- Extend the adapter only through public imports and normalize returned artifact
  paths/template provenance into project-owned values.
- Add a public API contract test covering callable shape and the minimum result
  fields/behavior required by multicuts.
- Add hermetic adapter tests using the public boundary or faithful fakes.

## Acceptance criteria

- No `multicuts` module imports a private `multisubs` package path.
- The accepted public operation consumes existing timed transcript/cues and
  does not invoke ASR.
- Target layout is derived from the actual package 014 raw clip/final geometry.
- Requested/resolved template and source/base metadata are preserved when the
  provider exposes them.
- Unsupported provider versions fail with an actionable compatibility error.
- The contract test fails clearly if the public operation/schema disappears.

## Tests and validation

```bash
pytest tests/contract -k "multisubs and subtitle"
pytest tests/unit -k "multisubs and subtitle"
ruff format --check .
ruff check .
pyright
```

## Blocker and exclusions

- This task remains blocked until the required capability is available through
  a supported public `multisubs` API (or the product requirement is explicitly
  revised). Do not work around it with private imports or per-clip ASR.
- Changes to the `multisubs` repository/release are external coordination and
  are not implementation scope for this plan package.
- As verified on 2026-09-23, the latest supported release is
  [`v4.2.0`](https://github.com/denilson-santos/multisubs/releases/tag/v4.2.0),
  whose [public package exports](https://github.com/denilson-santos/multisubs/blob/v4.2.0/multisubs/__init__.py)
  include transcription and ASS embedding but no subtitle-artifact builder.
