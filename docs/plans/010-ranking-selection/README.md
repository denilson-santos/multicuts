# Package 010: Ranking and Selection

| Field | Value |
| --- | --- |
| Milestone | M2 — Intelligence |
| Status | completed |
| Priority | P1 |
| Depends on | 009 Explainable heuristic scoring |
| Unlocks | Boundary refinement and media-output packages |
| PRs | [#35](https://github.com/denilson-santos/multicuts/pull/35) |

## Objective and expected outcome

Select up to the requested `K` strongest candidates above `min_score` using a
deterministic order, temporal-overlap suppression, and an extensible redundancy
policy. Completion produces project-owned selected candidates ready for
boundary refinement without silently changing their scored semantic spans.

## Context

FR-RANK-001–004 define top-K thresholding, temporal overlap, selection order,
and a future-capable semantic diversity policy. The initial implementation can
use deterministic text similarity, but its interface must not equate all
redundancy with temporal overlap.

## Included scope

- selected-candidate values containing candidate identity, rank, and original
  scored interval;
- deterministic score/confidence/completeness/source-time ordering;
- the documented temporal-overlap ratio and explicit threshold;
- greedy top-K selection that honors `clips` and `min_score`;
- a narrow redundancy policy with simple deterministic text similarity when
  justified;
- selection artifact persistence or scored-artifact extension sufficient for
  the next stage;
- pipeline integration and hermetic ranking/golden tests.

## Out of scope

- embeddings or a remote semantic-diversity provider;
- boundary refinement, padding, rescoring changed text spans, or rendering;
- final clip rank metadata files and complete run manifest;
- changing score arithmetic during ranking;
- guaranteeing exactly `K` results when too few candidates qualify.

## Requirements and established decisions

- [PRD: ranking, overlap, and diversity](../../prd.md#98-ranking-overlap-and-diversity)
- [PRD: score preservation](../../prd.md#fr-bnd-003--score-preservation)
- [Architecture: candidate ranking](../../architecture.md#candidatesrankingpy)
- [Architecture: pipeline](../../architecture.md#pipelinepy)
- [Conventions: scoring](../../conventions.md#16-scoring-conventions)

## Likely components

- selection-related additions to `src/multicuts/models.py`
- `src/multicuts/candidates/ranking.py`
- stage-specific selection persistence in `src/multicuts/artifacts.py`
- orchestration in `src/multicuts/pipeline.py`
- `tests/unit/` and ranking golden fixtures

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define ranking primitives and order](001-define-ranking-primitives.md) | completed | P1 | Package 009 | [#35](https://github.com/denilson-santos/multicuts/pull/35) | Valid selected-candidate values and deterministic total order |
| [002 Implement overlap and redundancy policies](002-implement-redundancy-policies.md) | completed | P1 | 001 | [#35](https://github.com/denilson-santos/multicuts/pull/35) | Explainable temporal suppression and an extensible diversity boundary |
| [003 Select and persist top-K candidates](003-select-and-persist-top-k.md) | completed | P1 | 002 | [#35](https://github.com/denilson-santos/multicuts/pull/35) | Thresholded, non-redundant, reusable selection results |
| [004 Integrate selection into the pipeline](004-integrate-selection-stage.md) | completed | P1 | 003 | [#35](https://github.com/denilson-santos/multicuts/pull/35) | Intelligence pipeline reaches selected candidates and stops before M3 |

## Suggested task sequence

Define the static order before adding contextual redundancy decisions. Build and
persist the complete top-K selection on those pure policies, then integrate the
stage and move the pipeline stopping point to the M3 handoff.

## Completion criteria

- Selection returns at most `K`, includes no score below `min_score`, and may
  validly return fewer or none.
- Temporal overlap uses the documented intersection-over-shorter-interval metric
  with an explicit tested threshold.
- Ordering is deterministic across input permutations and uses source time only
  as the stable final tie-breaker.
- No selected pair violates the active temporal-overlap policy unless a named
  configuration explicitly permits it.
- Redundancy decisions are explainable and persisted with stable reason codes.
- Selection preserves candidate IDs, score results, and original intervals for
  later boundary-refinement traceability.
- Standard non-integration validation passes.

## Risks, assumptions, and open questions

- Boundary refinement may later alter intervals. The next package must retain
  the scored span and rescore or mark material text changes as required by
  FR-BND-003.

## Implementation decisions

- Temporal overlap uses the documented intersection-over-shorter-interval
  metric. The initial default is `0.60`, equality suppresses the weaker
  candidate, and `--overlap-threshold` configures it.
- Non-temporal redundancy uses a replaceable policy. The initial local policy
  computes Jaccard similarity over case-folded alphanumeric token sets, defaults
  to the inclusive `0.90` threshold, and is configurable with `--text-threshold`.
- Static semantic completeness comes from the validated `standalone_context`
  score dimension. Ranking does not create or recompute a semantic judgment.
