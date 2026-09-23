# Task 010.003: Select and Persist Top-K Candidates

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 010.002 Implement overlap and redundancy policies |
| PR | [#35](https://github.com/denilson-santos/multicuts/pull/35) |

## Objective

Greedily select and rank up to `K` qualifying candidates, persist decisions, and
retain suppression evidence.

## Context and inputs

FR-RANK-001 permits fewer than `K` when too few candidates meet `min_score`.
Selection must consider stronger candidates first and keep traceable reasons for
non-selection.

## Expected changes

- Filter candidates below `min_score` before top-K selection.
- Traverse deterministic order and suppress candidates redundant with stronger
  already-selected values.
- Assign contiguous one-based ranks only to selected candidates.
- Retain explicit below-threshold, overlap, redundancy, and budget-exhausted
  statuses for evaluated candidates.
- Persist/reuse a versioned selection result keyed by scored-candidate identity,
  `K`, minimum score, policy versions, and thresholds.
- Add golden fixtures for ties, all-below-threshold, overlap chains, and fewer
  than `K` results.

## Acceptance criteria

- Output contains no more than `K` candidates and ranks are contiguous from one.
- Every selected score meets `min_score` and every suppression reason identifies
  the stronger candidate/policy when applicable.
- Reordering identical inputs does not change selection or ranks.
- Selection cache invalidates on score, `K`, threshold, or policy changes but not
  on subtitle/geometry configuration.
- An empty eligible set is a valid result, not an unexpected exception.

## Tests and validation

```bash
pytest tests/unit -k "top_k or selection"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Greedy selection is the documented initial direction, not an optimal global
  diversity solver.
- Final per-clip metadata and run manifest publication remain M3 work.
