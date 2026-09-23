# Package 013: Boundary Refinement

| Field | Value |
| --- | --- |
| Milestone | M3 — Media output |
| Status | in-progress |
| Priority | P1 |
| Depends on | 010 Ranking and selection |
| Unlocks | 014 Clip rendering; 015 clip-local transcript extraction |
| PRs | — |

## Objective and expected outcome

Turn each selected candidate's scored interval into a clean, source-bounded
render interval using real transcript timing, nearby pauses, and explicit
padding while preserving the selected semantic content and its score
provenance.

## Context

FR-BND-001–003 place refinement after selection and require small local
adjustments rather than candidate regeneration. The refined interval must remain
traceable to the scored span; a material text change cannot silently inherit an
unmodified score.

## Included scope

- typed refined-interval results and reason/provenance values;
- word/segment/pause-aware start and end adjustment in a bounded neighborhood;
- configurable pre-roll/post-roll with source-boundary clamping;
- explicit detection and handling of material transcript-span changes;
- deterministic persistence/reuse and pipeline integration;
- unit tests for source edges, missing word timing, and score preservation.

## Out of scope

- audio zero-crossing analysis or content-aware video edits;
- candidate regeneration, ranking changes, or semantic deduplication;
- FFmpeg cutting, aspect-ratio conversion, subtitles, or final publication;
- inventing missing word timestamps;
- silently rescoring through a remote provider.

## Requirements and established decisions

- [PRD: boundary refinement](../../prd.md#99-boundary-refinement)
- [PRD: single transcription](../../prd.md#p-006--single-transcription-multiple-derivatives)
- [Architecture: boundary refinement](../../architecture.md#10-boundary-refinement)
- [Architecture: pipeline](../../architecture.md#pipelinepy)
- [Conventions: media time values](../../conventions.md#time-values)

## Likely components

- refined-selection values in `src/multicuts/models.py`
- a focused boundary-refinement module near the candidate subsystem
- stage-specific persistence in `src/multicuts/artifacts.py`
- orchestration in `src/multicuts/pipeline.py`
- deterministic fixtures in `tests/unit/`

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define refined interval contracts](001-define-refined-interval-contracts.md) | in-progress | P1 | Package 010 | — | Traceable scored and render spans with validated bounds |
| [002 Implement deterministic boundary refinement](002-implement-boundary-refinement.md) | in-progress | P1 | 001 | — | Cleaner word/pause-aligned cuts with bounded padding |
| [003 Preserve score meaning and integrate refinement](003-preserve-score-and-integrate.md) | in-progress | P1 | 002 | — | Persisted refined selections that cannot silently inherit invalid scores |

## Suggested task sequence

Define the distinction between scored and render intervals first. Implement the
pure timing algorithm against transcript fixtures next. Add material-change
handling, persistence, and orchestration only after the interval invariants are
covered by tests.

## Completion criteria

- Every refined result retains candidate ID, rank, scored interval, refined
  interval, applied padding, reason codes, and refinement version.
- Refinement searches only a configured small neighborhood and remains within
  source duration and non-negative time.
- Starts/ends prefer real word or segment timing and natural pauses; absent word
  timing is handled conservatively and never invented.
- Default pre-roll/post-roll are explicit implementation decisions derived from
  the suggested `0.15s`/`0.25s` values and remain configurable.
- Material transcript-span changes are rejected or marked for explicit
  rescoring; they never silently retain the old score as equivalent.
- Identical inputs/configuration produce identical refined intervals.
- Standard non-integration validation passes.

## Risks, assumptions, and open questions

- The PRD does not quantify the search neighborhood or material text change.
  Tasks 001–003 must define versioned thresholds with invariant tests rather
  than embed unexplained magic values.
- ASR timestamps can be incomplete or noisy. Conservative unchanged boundaries
  are preferable to fabricated precision.
- This package does not require semantic-provider package 012; any explicit
  rescoring path must work through the configured scorer boundary.

## Implementation decisions

- Refinement searches at most `0.5` seconds on either side of each selected
  boundary. A measured gap of at least `0.4` seconds counts as a pause. These
  thresholds belong to refinement version `boundary-refinement-v1`.
- Default padding is `0.15` seconds before and `0.25` seconds after the semantic
  cut; `--pre-roll` and `--post-roll` configure it per run.
- A changed set of observed transcript word or segment indexes marks the result
  `requires_rescore`. Such a result retains the selected score only as provenance,
  and downstream rendering must not treat it as an approved score for the new
  content. With no usable timing evidence, boundaries remain unchanged.
