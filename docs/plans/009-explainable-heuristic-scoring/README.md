# Package 009: Explainable Heuristic Scoring

| Field | Value |
| --- | --- |
| Milestone | M2 — Intelligence |
| Status | planned |
| Priority | P1 |
| Depends on | 008 Candidate evaluation |
| Unlocks | 010 Ranking and selection; future semantic/hybrid scorer integration |
| PRs | — |

## Objective and expected outcome

Produce validated, versioned, explainable `0..100` score results from persisted
deterministic features and checklist outcomes. Completion makes the CLI's
established `heuristic` scorer mode operational and provides project-owned
score contracts that later semantic or hybrid providers can feed without
changing final composition rules.

## Context

The current CLI defaults to `--scorer heuristic`. FR-SCORE-001–009 define score
meaning, dimensions, penalties, result shape, provider separation, and
versioning. The exact heuristic mapping and penalty points are not prescribed,
so implementation must record them as algorithm-versioned decisions rather
than imply statistical calibration.

## Included scope

- typed dimension, penalty, and score-result contracts;
- validation of ranges, required dimensions, confidence, and explanation;
- the documented `scoring-v1` dimension weights;
- deterministic heuristic dimension values from package 008 evidence;
- project-owned weighted composition, penalty application, and clamping;
- versioned heuristic-scoring artifact persistence and reuse;
- `heuristic` pipeline/CLI routing with hermetic tests.

## Out of scope

- selection of a semantic provider or remote model;
- semantic-provider adapters, prompts, retries, or hybrid execution;
- fabricated semantic-provider confidence or reasons;
- final top-K ranking/deduplication, rendering, per-clip JSON, or run manifest;
- claims that the score is a probability of virality.

## Requirements and established decisions

- [PRD: scoring](../../prd.md#97-scoring)
- [PRD: explainability](../../prd.md#p-001--explainability)
- [Architecture: scoring adapter boundary](../../architecture.md#73-adaptersscoringpy)
- [Architecture: scoring architecture](../../architecture.md#9-scoring-architecture)
- [Architecture: scoring cache](../../architecture.md#scoring-cache-key)
- [Conventions: scoring](../../conventions.md#16-scoring-conventions)

## Likely components

- score-related additions to `src/multicuts/models.py`
- a small project-owned scoring module for validation/composition
- `src/multicuts/scoring/heuristic.py` or the repository's nearest equivalent
- score artifact behavior in `src/multicuts/artifacts.py`
- scorer routing in `src/multicuts/pipeline.py`
- `tests/unit/` and stable scoring fixtures

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define versioned score contracts](001-define-score-contracts.md) | planned | P1 | Package 008 | — | Valid score dimensions, confidence, penalties, reason, and provenance |
| [002 Implement heuristic judgments](002-implement-heuristic-judgments.md) | planned | P1 | 001 | — | Deterministic dimension evidence without fabricated provider output |
| [003 Compose final scores and penalties](003-compose-scores-and-penalties.md) | planned | P1 | 002 | — | Reproducible weighted `0..100` results under `scoring-v1` |
| [004 Persist and integrate heuristic scoring](004-persist-and-integrate-scoring.md) | planned | P1 | 003 | — | Reusable scored candidates and an operational heuristic pipeline path |

## Suggested task sequence

Stabilize the score schema first, implement evidence-based heuristic judgments
second, and compose project-owned weights/penalties third. Persist and route the
fully reproducible result only after those three contracts have invariant tests.

## Completion criteria

- Score results always validate to the documented seven dimensions, finite
  confidence, structured penalties, explanation, and `0..100` final score.
- With fixed inputs, weights, thresholds, and algorithm version, heuristic
  output is reproducible.
- The persisted components are sufficient to recompute the final score from
  dimension values and penalties.
- No heuristic result claims semantic-provider provenance or fabricates a remote
  response.
- Weight/threshold/algorithm changes invalidate scoring reuse; transcript,
  feature, geometry, and subtitle caches retain their documented independence.
- CLI/pipeline routing rejects unsupported scorer names with `ScoringError` and
  advances honestly to the selection boundary.
- Standard non-integration validation passes.

## Risks, assumptions, and open questions

- The PRD specifies dimension weights but not how deterministic evidence maps to
  every dimension or how many points each penalty removes. Tasks 002–003 must
  publish these as `scoring-v1` implementation decisions with invariant tests.
- Semantic concepts such as hook and payoff cannot be measured perfectly by
  simple heuristics. Reasons must describe the evidence actually used and avoid
  pretending a semantic model ran.
- A future semantic/hybrid package must choose a provider/model and validate its
  structured response. It should reuse the contracts and composition established
  here rather than make provider output authoritative.
- The meaning of heuristic confidence needs an explicit deterministic definition
  (for example, evidence completeness), not a probability claim.
