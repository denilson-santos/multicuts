# Task 004.003: Handle Media Preflight Failures

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 004.002 Probe media and normalize geometry |

## Objective

Reject unavailable tools and unusable media with actionable errors before the
transcription provider or other expensive work is loaded.

## Context and inputs

FR-MEDIA-001/002 require FFmpeg and ffprobe availability, a usable video stream,
duration, geometry, and usable audio. Edge cases include missing FFmpeg, missing
audio, silence, rotation, and invalid media.

## Expected changes

- Check FFmpeg and ffprobe availability through narrow process calls.
- Validate the normalized probe result before transcription.
- Reject missing video, missing usable audio, invalid/non-positive duration, and
  unusable geometry with `MediaError`.
- Preserve safe command failure context without exposing full command content or
  unbounded output.
- Ensure the pipeline orders configuration, acquisition, and media preflight
  before transcription.

## Suggested sequence

1. Add tool-presence/version probes with bounded diagnostics.
2. Add a pure validator for required `MediaInfo` invariants.
3. Integrate preflight ordering at the pipeline boundary.
4. Test every failure category with process-boundary stubs.
5. Mark real binary checks as integration tests.

## Acceptance criteria

- Missing FFmpeg or ffprobe produces an actionable `MediaError`.
- A video without usable audio is rejected before any transcription call.
- Invalid duration/geometry/streams cannot reach package 005.
- Error messages include safe operation/resource context and preserve causes.
- The default test suite invokes no external executable.

## Tests and validation

```bash
pytest tests/unit -k "preflight or media_error"
pytest -m integration -k "ffmpeg or ffprobe"
ruff format --check .
ruff check .
pyright
```

The integration command is conditional on local binaries.

## Implementation decisions

- `probe_media` checks that `ffmpeg` and `ffprobe` can start with `-version`
  before reading probe JSON. Version checks have a five-second timeout and do
  not surface provider output or local executable paths in errors.
- Probe normalization keeps audio availability explicit in `MediaInfo`; the
  transcription preflight rejects a normalized result without a usable audio
  stream. Duration, video stream, and geometry validation remain in the
  normalization boundary and `MediaInfo` invariants.
- The pipeline task 003.002 calls `probe_media` after acquisition, so these
  checks run before later transcription is added without coupling either
  branch to an unmerged API.

## Risks and exclusions

- Detecting a nearly silent track requires data beyond simple stream presence;
  document it as a later media-analysis rule unless this package has a confirmed
  low-cost signal.
- Verifying the FFmpeg subtitles filter is needed before rendering, not before
  source transcription, unless the pipeline intentionally validates all runtime
  capabilities up front.
- Do not load `multisubs` or WhisperX during preflight.
