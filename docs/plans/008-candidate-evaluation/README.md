# Package 008: Candidate Evaluation

| Field | Value |
| --- | --- |
| Milestone | M2 — Intelligence |
| Status | planned |
| Priority | P1 |
| Depends on | 007 Semantic candidates |
| Unlocks | 009 Explainable heuristic scoring |
| PRs | — |

## Objective and expected outcome

Evaluate generated candidates with reusable deterministic features and explicit
checklist outcomes, discard hard failures, and cap the shortlist passed to more
expensive scoring. Completion persists enough traceable metadata to explain why
a candidate passed, remained with warnings, or was rejected.

## Context

FR-FLT-001–003 require `PASS`, `SOFT_FAIL`, `HARD_FAIL`, or `UNKNOWN` for every
rule and persistence of every non-pass result. FR-CAN-004 and NFR-PERF-002
require cheap filtering and deterministic signals before semantic scoring, with
a configurable upper bound on candidates sent downstream.

## Included scope

- typed deterministic feature and checklist result models;
- only features consumed by the initial checklist or package 009 scorer;
- documented initial rules for duration, speech amount, pause/silence evidence,
  boundary quality, standalone context signals, payoff signals, and transcript
  quality;
- deterministic hard-filter behavior and soft-fail traceability;
- an explicit candidate scoring budget and cheap deterministic pre-order;
- safe, versioned candidate-evaluation artifact persistence;
- pipeline integration and hermetic tests.

## Out of scope

- semantic-provider calls or semantic judgments presented as provider output;
- final `0..100` score composition and score penalties;
- overlap deduplication against stronger scored candidates;
- embedding-based similarity, boundary refinement, rendering, or final manifest;
- features with no consumer in this package or package 009.

## Requirements and established decisions

- [PRD: candidate budget](../../prd.md#fr-can-004--candidate-budget)
- [PRD: hard filters and checklist](../../prd.md#96-hard-filters-and-checklist)
- [Architecture: candidate filters](../../architecture.md#candidatesfilterspy)
- [Architecture: deterministic features](../../architecture.md#candidatesfeaturespy)
- [Architecture: performance](../../architecture.md#18-performance-constraints)
- [Conventions: filesystem](../../conventions.md#12-filesystem-conventions)

## Likely components

- candidate-evaluation additions to `src/multicuts/models.py`
- a candidate-budget field in `src/multicuts/config.py` and its CLI mapping when
  the user-facing option is established
- `src/multicuts/candidates/features.py`
- `src/multicuts/candidates/filters.py`
- candidate artifact behavior in `src/multicuts/artifacts.py`
- orchestration in `src/multicuts/pipeline.py`
- `tests/unit/` and small candidate fixtures

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define feature and checklist contracts](001-define-evaluation-contracts.md) | planned | P1 | Package 007 | — | Typed reusable features and explicit rule outcomes |
| [002 Compute deterministic features](002-compute-deterministic-features.md) | planned | P1 | 001 | — | Tested structural and transcript-quality evidence |
| [003 Apply checklist rules and scoring budget](003-apply-checklist-and-budget.md) | planned | P1 | 002 | — | Hard-filtered, traceable, bounded shortlist |
| [004 Persist and integrate candidate evaluation](004-persist-and-integrate-evaluation.md) | planned | P1 | 003 | — | Reusable candidate artifact and pipeline handoff to scoring |

## Suggested task sequence

Complete the typed contracts before feature computation, then bind only those
features to rules and budget behavior. Add persistence/orchestration last so the
artifact schema reflects the established evaluation model instead of driving it.

## Completion criteria

- Every implemented rule returns exactly one explicit outcome with a stable rule
  code and human-readable reason where relevant.
- Every `SOFT_FAIL`, `HARD_FAIL`, and `UNKNOWN` outcome is present in persisted
  candidate metadata.
- Features are deterministic from project-owned transcript/candidate data and
  do not invoke remote providers or media tools.
- Hard failures never reach scoring; the remaining shortlist never exceeds its
  configured budget.
- Cheap pre-ordering and budget ties are deterministic and do not masquerade as
  the final viral-potential score.
- Artifact writes are versioned, UTF-8, validated, and cannot expose partial
  completed-looking JSON.
- Standard non-integration validation passes.

## Risks, assumptions, and open questions

- The PRD does not select candidate-budget defaults or whether the cap scales
  per source hour. Task 003 must record an initial bounded policy before changing
  `RunConfig`/CLI behavior; this is an implementation decision, not a product
  quality claim.
- Silence is not fully observable from transcript gaps alone. Rules must report
  `UNKNOWN` when evidence is insufficient rather than claim audio analysis that
  did not occur.
- Standalone context and payoff checks are cheap heuristics here. Semantic
  judgments belong to a future semantic scorer and must not be fabricated.
- Candidate artifact invalidation must include generator/evaluation versions and
  relevant duration/budget configuration without coupling to subtitle styling.
