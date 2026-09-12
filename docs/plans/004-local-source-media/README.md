# Package 004: Local Source and Media

| Field | Value |
| --- | --- |
| Milestone | M1 — Source and transcript |
| Status | in-progress |
| Priority | P1 |
| Depends on | 002 Domain foundation |
| Unlocks | 005 Multisubs transcription |

## Objective and expected outcome

Turn a valid local video path into an `AcquiredSource`, give it a stable
fingerprint, and probe it into normalized `MediaInfo` before any transcription
model is loaded.

## Context

Local input is the smallest product path and is required by goal G-001. The PRD
requires early rejection of invalid paths, missing tools, unusable video/audio,
and incorrect assumptions about rotated presentation geometry.

## Included scope

- local path validation without modifying the source;
- deterministic source fingerprinting suitable for transcription cache keys;
- FFmpeg/ffprobe availability checks;
- ffprobe invocation and normalization of duration, streams, coded dimensions,
  rotation, sample aspect ratio/presentation geometry, and usable audio;
- translation into `AcquisitionError` and `MediaError`;
- hermetic unit tests and explicitly marked integration tests.

## Out of scope

- URLs, YouTube, yt-dlp, cookies, and downloaded-source retention;
- transcription and transcript persistence;
- cutting, aspect-ratio conversion, subtitle filters, and rendering;
- a generic subprocess or media framework.

## Requirements and established decisions

- [PRD: acquisition](../../prd.md#92-acquisition)
- [PRD: media probing](../../prd.md#93-media-probing)
- [Architecture: `media.py`](../../architecture.md#mediapy)
- [Architecture: state and side effects](../../architecture.md#16-state-and-side-effects)
- [Conventions: filesystem](../../conventions.md#12-filesystem-conventions)
- [Conventions: FFmpeg and ffprobe](../../conventions.md#13-ffmpeg-and-ffprobe-conventions)

## Likely components

- a narrow local-source function or module returning `AcquiredSource`
- `src/multicuts/media.py`
- `tests/unit/`
- `tests/integration/`

## Task index

| Task | Status | Depends on | Outcome |
| --- | --- | --- | --- |
| [001 Acquire and fingerprint local source](001-acquire-and-fingerprint-local-source.md) | completed | Package 002 | Validated immutable local source description |
| [002 Probe media and normalize geometry](002-probe-media-and-normalize-geometry.md) | in-progress | 001 | Accurate `MediaInfo` from ffprobe data |
| [003 Handle media preflight failures](003-handle-media-preflight-failures.md) | planned | 002 | Actionable early failures and integration coverage |

## Completion criteria

- Missing paths and directories are rejected without touching their contents.
- A valid local file produces a stable fingerprint and safe metadata.
- Media probing distinguishes coded dimensions from final presentation geometry.
- Missing FFmpeg/ffprobe, missing video, and missing usable audio fail before
  transcription.
- Subprocesses use argument lists and never `shell=True`.
- Default tests do not require FFmpeg; marked integration tests exercise the real
  boundary when available.

## Risks, assumptions, and open questions

- The PRD permits several fingerprint strategies but does not choose an
  algorithm. Select and version a deterministic strategy before task 001; do not
  rely only on a filename or mutable path.
- Hashing large local files can be expensive. Any optimization must preserve the
  requirement that the identity changes with the effective input.
- Exact interpretation of rotation and sample aspect ratio must be verified with
  small fixtures and explicit dimension tolerances.
