# Package 014: Clip Rendering

| Field | Value |
| --- | --- |
| Milestone | M3 — Media output |
| Status | completed |
| Priority | P1 |
| Depends on | 004 Local source and media; 013 Boundary refinement |
| Unlocks | 015 Clip subtitles; final clip publication for subtitle-disabled runs |
| PRs | [#38](https://github.com/denilson-santos/multicuts/pull/38) |

## Objective and expected outcome

Render each refined interval accurately with FFmpeg in `original` or `9:16`
mode, using normalized presentation geometry and safe temporary publication.
Completion produces a validated final-geometry raw clip that can be published
directly when subtitles are disabled or passed to package 015 for burn-in.

## Context

FR-REN-001–004 and FR-REN-009 require FFmpeg, accurate timestamps, original and
center-cropped vertical modes, and protection against partial/overwritten final
files. Subtitle layout is deliberately downstream because it must use the
rendered final geometry.

## Included scope

- project-owned render request/result/config contracts;
- narrow FFmpeg command construction and safe subprocess execution;
- accurate source trimming with explicit audio/video mapping;
- source-presentation-aware `original` rendering;
- center crop and configurable resize for `9:16` (default target `1080x1920`);
- temporary output, validation, atomic publication, and no silent overwrite;
- rendering cache identity and synchronous pipeline integration;
- hermetic command tests plus marked FFmpeg integration tests.

## Out of scope

- face tracking, smart reframing, manual crop offsets, or arbitrary aspect
  ratios;
- subtitle artifact generation or burn-in;
- stream-copy optimization that compromises timing/geometry consistency;
- final run manifest and complete per-clip metadata;
- generic media-processing frameworks or shell execution.

## Requirements and established decisions

- [PRD: rendering](../../prd.md#910-rendering)
- [PRD: failed render safety](../../prd.md#ac-009--failed-render-safety)
- [Architecture: raw clip rendering](../../architecture.md#111-raw-clip-rendering)
- [Architecture: workspace and artifacts](../../architecture.md#12-workspace-and-artifacts)
- [Architecture: rendering cache](../../architecture.md#rendering-cache-key)
- [Conventions: FFmpeg and ffprobe](../../conventions.md#13-ffmpeg-and-ffprobe-conventions)

## Likely components

- render values in `src/multicuts/models.py`
- `src/multicuts/rendering/cutter.py`
- a narrow reusable FFmpeg execution helper near the media boundary
- render paths/cache metadata in `src/multicuts/rendering/artifacts.py`
- orchestration in `src/multicuts/pipeline.py`
- unit and marked integration tests with small generated fixtures

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define rendering contracts and FFmpeg boundary](001-define-rendering-contracts.md) | completed | P1 | Packages 004, 013 | [#38](https://github.com/denilson-santos/multicuts/pull/38) | Valid render requests/results and inspectable argument-list commands |
| [002 Render accurate original-geometry clips](002-render-original-clips.md) | completed | P1 | 001 | [#38](https://github.com/denilson-santos/multicuts/pull/38) | Temporally accurate clips preserving presentation aspect ratio |
| [003 Render center-cropped vertical clips](003-render-vertical-clips.md) | completed | P1 | 002 | [#38](https://github.com/denilson-santos/multicuts/pull/38) | Valid configurable `9:16` output from normalized source geometry |
| [004 Publish, cache, and integrate raw clips](004-publish-and-integrate-rendering.md) | completed | P1 | 003 | [#38](https://github.com/denilson-santos/multicuts/pull/38) | Safe reusable raw clips at the subtitle/final-output handoff |

## Suggested task sequence

Stabilize render models, paths, and command construction before executing
FFmpeg. Make original-mode trim correctness work first, add `9:16` geometry
second, then layer safe publication/cache behavior and pipeline orchestration on
the shared renderer.

## Completion criteria

- Both aspect-ratio modes render the exact refined interval within explicit
  media-test tolerances and map intended audio/video streams.
- `original` preserves source presentation aspect ratio within tolerance,
  including normalized rotation handling from package 004.
- `9:16` performs center crop and resize to a validated configurable vertical
  target, defaulting to `1080x1920` when that default is adopted.
- FFmpeg commands are argument lists with no `shell=True`, and bounded safe
  diagnostics become `RenderingError`s with causes preserved.
- Incomplete output remains private; an existing completed file is never
  overwritten silently.
- A successful raw result records final geometry and renderer/version inputs
  needed by subtitle layout and cache identity.
- Standard tests remain hermetic; FFmpeg-dependent tests are explicitly marked.

## Risks, assumptions, and open questions

- Rotation and display geometry can differ from coded width/height. Commands
  must consume normalized presentation metadata rather than recalculate it
  inconsistently.
- The vertical default is `1080x1920`. Alternate targets must have even,
  positive dimensions and an exact `9:16` ratio.
- Cache reuse must validate the completed media artifact, not trust metadata
  alone. Detailed invalid-cache hardening may continue in M4.

## Completion record

- PR [#38](https://github.com/denilson-santos/multicuts/pull/38) was merged into `main` at commit `5dfb446`.
- GitHub Actions run [#35898238448](https://github.com/denilson-santos/multicuts/actions/runs/35898238448) passed Python 3.10 quality and Python 3.13 compatibility checks.
- The package passed the hermetic suite and four marked FFmpeg integration tests before integration.
