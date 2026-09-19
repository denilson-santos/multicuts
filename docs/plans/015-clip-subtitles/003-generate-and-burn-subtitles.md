# Task 015.003: Generate and Burn Final-Geometry Subtitles

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 015.002 Establish the public `multisubs` subtitle-artifact contract; Package 014 Clip rendering |
| PR | — |

## Objective

Generate styled subtitle artifacts for each raw final-geometry clip and burn
them into a safely produced final video.

## Context and inputs

Layout, wrapping, apparent font size, and safe areas depend on the actual raw
clip geometry. `multicuts` coordinates this flow while `multisubs` owns template,
font, animation, and ASS-generation behavior.

## Expected changes

- Call the task 002 public adapter operation with the raw clip,
  `ClipTranscript`, requested template/template directory, and controlled work
  path.
- Validate returned subtitle artifacts before burn-in.
- Use the public `multisubs` embedding operation (or its supported public
  equivalent) to render to a temporary final-video path.
- Enable word animation/highlighting only when safe aligned word timing exists;
  otherwise use supported cue-level behavior or fail clearly.
- Validate completed video timing/geometry and publish only after success.
- Add hermetic adapter/coordinator tests and marked FFmpeg/`multisubs`
  integration coverage.

## Acceptance criteria

- Subtitle generation receives actual final clip geometry rather than source
  geometry.
- The output contains hard subtitles when subtitle rendering is enabled.
- The operation performs no ASR and uses only source-derived clip timing.
- Missing/invalid template, subtitle artifact, or burn-in output raises an
  actionable `RenderingError` without publishing a partial final clip.
- Original and `9:16` outputs retain package 014 timing and geometry within
  explicit tolerances.
- Provider implementation details do not escape `MultisubsAdapter`.

## Tests and validation

```bash
pytest tests/unit -k "subtitle and (render or multisubs)"
pytest -m integration -k "subtitle"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Visual golden tests may be appropriate for selected layouts but should remain
  small and version-aware; they do not replace public contract tests.
- Do not recreate templates or animation behavior in multicuts to avoid the
  external API blocker.
