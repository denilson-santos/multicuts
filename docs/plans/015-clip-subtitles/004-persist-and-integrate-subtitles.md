# Task 015.004: Persist Provenance and Integrate Subtitle Rendering

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 015.003 Generate and burn final-geometry subtitles |
| PR | [#41](https://github.com/denilson-santos/multicuts/pull/41) |

## Objective

Persist subtitle/render provenance, reuse compatible artifacts, and hand final
clips to package 016 without coupling earlier stages to styling options.

## Context and inputs

Changing only template/style should invalidate subtitle artifacts and the final
burned video, not transcription, deterministic features, scoring, selection,
refinement, or the geometry-compatible raw clip.

## Expected changes

- Persist `ClipTranscript`, subtitle artifact metadata, requested/resolved
  template provenance, provider version, final geometry, and final output path.
- Key subtitle reuse by clip transcript/refined interval, raw clip identity,
  template/config, geometry, and provider/renderer versions.
- Integrate subtitle-enabled and subtitle-disabled branches into one readable
  synchronous pipeline.
- Retain useful intermediates only under established workspace policy and
  `--keep-intermediates` behavior.
- Add tests for template change invalidation, cache hits, mixed multi-clip
  failures, no-subtitle flow, and no repeated transcription.

## Acceptance criteria

- Compatible subtitle/final render artifacts are reused without provider work
  or FFmpeg burn-in.
- Template/style changes invalidate only subtitle-dependent artifacts.
- No pipeline path calls the transcription adapter for a selected clip.
- Requested/resolved template, template source/base, and provider version are
  available to package 016 when exposed by `multisubs`.
- Subtitle-disabled runs publish the validated raw clip through the same final
  clip handoff with explicit `subtitles_enabled=false` provenance.
- A failed clip remains distinguishable from completed clips and publishes no
  partial final output.

## Tests and validation

```bash
pytest tests/unit -k "subtitle and (artifact or cache or pipeline)"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- This task records provider provenance but does not publish the complete run
  manifest or per-clip metadata schema.
- Cleanup hardening after interruption remains M4 work; completed-output safety
  is required here.

PR #41 merged this task and its CI checks passed. Unit and integration coverage
verified cache hits and template invalidation, subtitle-disabled publication,
single-source transcription, and preservation of completed clips when a later
clip fails.
