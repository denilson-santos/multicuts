# Task 004.002: Probe Media and Normalize Geometry

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 004.001 Acquire and fingerprint local source |

## Objective

Invoke ffprobe through a narrow boundary and normalize usable media metadata into
`MediaInfo`, including final presentation geometry.

## Context and inputs

FR-MEDIA-001/003 require duration, usable video/audio, dimensions, rotation, and
the distinction between coded dimensions and presentation dimensions. Rendering
later depends on this distinction, but rendering commands are not part of this
task.

## Expected changes

- Build the ffprobe command as an argument list and request machine-readable
  output.
- Parse only fields needed for duration, stream selection, coded geometry,
  rotation/display metadata, sample aspect ratio, and audio availability.
- Normalize untyped JSON immediately into `MediaInfo`.
- Bound captured diagnostic output before including it in safe errors.
- Add fixture-driven parser tests for normal, rotated, anamorphic, missing-audio,
  and malformed responses.

## Suggested sequence

1. Define the exact ffprobe fields consumed by `MediaInfo`.
2. Separate command execution from pure response normalization.
3. Implement presentation-geometry calculation with explicit invariants.
4. Add fixtures and parameterized unit tests.
5. Add one marked integration test using a small media fixture when available.

## Acceptance criteria

- Probe commands never use `shell=True`.
- Normalized duration and dimensions are typed project values.
- A 90/270-degree rotation swaps presentation orientation correctly.
- Sample aspect ratio is considered where it affects displayed geometry.
- Missing/malformed required fields produce `MediaError` rather than leaking a
  provider dictionary or parser exception.

## Tests and validation

```bash
pytest tests/unit -k "probe or geometry"
pytest -m integration -k probe
ruff format --check .
ruff check .
pyright
```

Run the integration command only where ffprobe and the small fixture are
available; the unit suite must remain independent of them.

## Risks and exclusions

- Duration comes from the container format. A video stream is selected only when
  it has positive frame dimensions and is not attached cover art. An audio stream
  requires positive channels and sample rate; package task 004.003 decides when
  missing audio fails the run.
- Missing or `N/A` sample aspect ratio is treated as square pixels. Non-quarter-
  turn display rotation is rejected until its presentation geometry is verified
  with real fixtures; silently guessing would misplace subtitles later.
- Containers expose rotation through different metadata locations; fixtures must
  cover the supported interpretations.
- Do not assume the first video/audio stream is usable without explicit checks.
- Do not add crop, resize, subtitles-filter, or encoder logic.
