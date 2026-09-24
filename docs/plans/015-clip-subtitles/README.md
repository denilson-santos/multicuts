# Package 015: Clip Subtitles

| Field | Value |
| --- | --- |
| Milestone | M3 — Media output |
| Status | in-progress |
| Priority | P1 |
| Depends on | 005 Multisubs transcription; 006 Transcript cache; 013 Boundary refinement; 014 Clip rendering |
| Unlocks | Hard-subtitled final clips and subtitle provenance for package 016 |
| PRs | [#39](https://github.com/denilson-santos/multicuts/pull/39), [#40](https://github.com/denilson-santos/multicuts/pull/40) |

## Objective and expected outcome

Derive clip-local transcript timing from the single source transcript, build
subtitle artifacts through a supported public `multisubs` API for the rendered
final geometry, and burn them into final clips with template provenance and no
new ASR pass.

## Context

FR-REN-005–008 and decision D-011 require transcript reuse and final-geometry
layout. The supported `multisubs 4.3.0` timed-cue JSON contract creates styled SRT,
ASS, and a rendered video together from an existing transcript and raw clip.
Its public CLI accepts templates. Task 002 integrates that boundary; private
imports and per-clip ASR remain forbidden.

## Included scope

- `ClipTranscript` extraction, time shifting, clamping, and provenance;
- public-contract verification for subtitle artifact generation from existing
  timed transcript data and target video geometry;
- `MultisubsAdapter` normalization of subtitle artifacts and template metadata;
- safe hard-subtitle burn-in from the package 014 final-geometry raw clip;
- template/template-directory configuration, animations where timing permits,
  and renderer provenance;
- stage-specific subtitle/render reuse and pipeline integration;
- hermetic contract/adapter tests and marked media integration tests.

## Out of scope

- retranscribing each clip or inventing missing word timestamps;
- importing private `multisubs` transcriber/ASS/layout/template/animation
  modules;
- implementing a competing subtitle template/font/animation engine;
- face-aware positioning, new visual preset catalogs, or template design;
- complete run manifest/per-clip JSON publication, which belongs to package 016.

## Requirements and established decisions

- [PRD: rendering](../../prd.md#910-rendering)
- [PRD: `multisubs` per-clip flow](../../prd.md#186-recommended-per-clip-flow)
- [PRD: public timed-cue contract](../../prd.md#187-public-timed-cue-contract)
- [Architecture: clip-local transcript](../../architecture.md#112-clip-local-transcript)
- [Architecture: subtitle rendering](../../architecture.md#113-subtitle-rendering)
- [Conventions: `multisubs`](../../conventions.md#15-multisubs-conventions)

## Likely components

- `ClipTranscript` and subtitle artifact/provenance values in
  `src/multicuts/models.py`
- public-only additions to `src/multicuts/adapters/multisubs.py`
- `src/multicuts/rendering/subtitles.py`
- subtitle paths/cache metadata in `src/multicuts/artifacts.py`
- orchestration in `src/multicuts/pipeline.py`
- public API contract tests plus unit/integration fixtures

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Derive clip-local transcripts](001-derive-clip-transcripts.md) | completed | P1 | Packages 006, 013 | [#39](https://github.com/denilson-santos/multicuts/pull/39) | Source-derived clip timelines with traceable real timestamps |
| [002 Establish the public `multisubs` subtitle-artifact contract](002-establish-multisubs-contract.md) | completed | P1 | 001; supported `multisubs` release/API | [#40](https://github.com/denilson-santos/multicuts/pull/40) | Public creation of styled subtitle artifacts without ASR |
| [003 Generate and burn final-geometry subtitles](003-generate-and-burn-subtitles.md) | in-progress | P1 | 002; Package 014 | — | Valid hard-subtitled clips using provider templates and real timing |
| [004 Persist provenance and integrate subtitle rendering](004-persist-and-integrate-subtitles.md) | in-progress | P1 | 003 | — | Cache-safe subtitle execution and final clip handoff |

## Suggested task sequence

Tasks 001 and 002 are integrated. Tasks 003 and 004 are being delivered
together: task 003 validates final-geometry subtitle burn-in, and task 004
connects it to the pipeline with reusable artifacts and provenance.

## Completion criteria

- Every clip transcript is derived from the source transcript, starts at clip
  time `0`, is clamped to clip duration, and preserves source indexes/provenance.
- No selected clip triggers another transcription/ASR operation.
- All `multisubs` use is through supported public APIs covered by a contract
  test for the accepted `>=4.3,<5` range or a deliberately narrowed compatible
  range.
- Subtitle layout is resolved against the probed raw clip geometry, including
  the final `9:16` crop/resize.
- Requested/resolved template, source/base, provider version, and relevant
  artifact paths are retained when exposed by the public provider contract.
- Word animations/highlighting are used only with safe aligned word timing.
- Failed burn-in publishes no partial final clip and does not destroy a valid
  raw intermediate.

## Risks, assumptions, and open questions

- The published v4.3.0 schema requires exact text-to-word mapping and complete
  word times. The adapter fails clearly when a clip cannot satisfy it.
- The CLI publishes SRT, ASS, and video together. Template source/base metadata
  is not returned, so only requested/resolved template name can be recorded
  until the provider exposes more provenance.
- The default recommended template remains an open product question. Existing
  configured CLI behavior should be preserved until explicitly changed.
- Template-only changes should invalidate subtitle/final render artifacts, not
  transcription, candidates, scores, or raw geometry rendering.
