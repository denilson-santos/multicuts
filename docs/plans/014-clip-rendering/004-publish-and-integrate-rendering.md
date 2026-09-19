# Task 014.004: Publish, Cache, and Integrate Raw Clips

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 014.003 Render center-cropped vertical clips |
| PR | — |

## Objective

Safely publish/reuse validated raw final-geometry clips and connect rendering to
the synchronous pipeline.

## Context and inputs

Raw clips are final only when subtitles are disabled; otherwise they are the
input to package 015. In both cases an incomplete render must remain private and
must never replace an existing completed file silently.

## Expected changes

- Allocate controlled temporary and final/raw clip paths per selected rank and
  stable identity.
- Publish only after FFmpeg success and ffprobe validation, using atomic replace
  only where the destination policy explicitly permits it.
- Refuse silent overwrite and define deterministic collision behavior for an
  existing completed output.
- Persist render metadata/cache identity from refined interval, source
  fingerprint, target geometry, renderer/version, and relevant options.
- Integrate rendering after refinement; bypass it for zero selected candidates.
- Add tests for cache hit/miss, failure cleanup, collision, multi-clip ordering,
  and subtitle-enabled handoff.

## Acceptance criteria

- A failed/interrupted render publishes no partial file as a completed clip.
- An existing completed destination is preserved unless an explicit future
  overwrite option authorizes replacement.
- Changing interval, geometry, or renderer-relevant configuration invalidates
  raw-render reuse; subtitle-only changes do not require retranscription or
  rescoring.
- Each successful result records a verified output path and final geometry.
- Subtitles-enabled runs expose the raw clip only to the subtitle stage and do
  not announce final completion prematurely.
- Default tests mock the FFmpeg boundary and remain hermetic.

## Tests and validation

```bash
pytest tests/unit -k "render and (artifact or pipeline or publish)"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Detailed cleanup of all abandoned work after interruption is M4 hardening,
  but final-output safety is required here.
- Do not couple raw-render cache identity to semantic provider or subtitle
  template configuration.
