# Task 015.002: Establish the Public `multisubs` Subtitle-Artifact Contract

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 015.001 Derive clip-local transcripts; a supported public `multisubs` release/API that builds subtitle artifacts from existing timed transcript data |
| PR | — |

## Objective

Verify and adapt a supported public `multisubs` contract that creates styled
subtitle artifacts for a target video from an existing `ClipTranscript`, with
no transcription step.

## Context and inputs

The supported multisubs 4.3.0 release exposes versioned timed-cue JSON input.
Its public API returns SRT, ASS, and the rendered video together. The CLI also
accepts template and template-directory options. Project rules forbid private
renderer/layout/template/animation imports.

## Expected changes

- Consume the public multisubs timed-cue JSON contract and CLI with an actual
  raw clip, template, optional template directory, and controlled output path.
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
  does not invoke ASR. Cues lacking complete word times fail clearly.
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

- The [v4.3.0 release](https://github.com/denilson-santos/multisubs/releases/tag/v4.3.0)
  published the required public timed-cue JSON and rendering contract on
  2026-09-24, clearing the external blocker.
- The schema requires every cue to have a nonempty, exactly mapped word list.
  Source clips with incomplete word timing need an explicit failure; inventing
  word times or running clip-level ASR remains excluded.
- Changes to the `multisubs` repository/release are external coordination and
  are not implementation scope for this plan package.
