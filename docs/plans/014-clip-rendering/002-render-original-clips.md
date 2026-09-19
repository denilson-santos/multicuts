# Task 014.002: Render Accurate Original-Geometry Clips

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 014.001 Define rendering contracts and the FFmpeg boundary |
| PR | — |

## Objective

Render temporally accurate clips while preserving normalized source
presentation aspect ratio.

## Context and inputs

The MVP prioritizes cut accuracy and consistent outputs over stream-copy speed.
Presentation geometry from media probing already accounts for rotation and must
remain the source of truth.

## Expected changes

- Build the accurate trim/transcode command for the refined source interval.
- Map intended video and audio streams explicitly and define behavior for
  sources without audio.
- Normalize rotation/display transforms without changing intended presentation
  aspect ratio.
- Validate completed temporary output with ffprobe before publication.
- Add unit tests for command shape and marked integration tests for duration,
  geometry, audio presence, and rotated fixtures when available.

## Acceptance criteria

- Rendered start/end and duration are within documented explicit tolerances of
  the requested refined interval.
- Display aspect ratio matches normalized source presentation geometry within
  tolerance.
- Audio/video stream handling is deterministic and missing optional audio has a
  clear supported or rejected behavior.
- A non-zero FFmpeg exit, missing output, or invalid probed result raises
  `RenderingError` and leaves no completed publication.
- Integration tests skip clearly when FFmpeg/ffprobe are unavailable.

## Tests and validation

```bash
pytest tests/unit -k "render and original"
pytest -m integration -k "render and original"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Container/codecs and keyframes can affect timestamp precision. Tests must use
  tolerances and inspect real output rather than assert command strings alone.
- Do not add stream-copy as a fallback when it can violate requested timing.
