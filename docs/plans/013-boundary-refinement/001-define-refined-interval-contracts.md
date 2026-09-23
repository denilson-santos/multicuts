# Task 013.001: Define Refined Interval Contracts

| Field | Value |
| --- | --- |
| Status | in-review |
| Priority | P1 |
| Depends on | Package 010 Ranking and selection |
| PR | [#37](https://github.com/denilson-santos/multicuts/pull/37) |

## Objective

Represent scored and render intervals separately with enough provenance to
validate source bounds and score preservation.

## Context and inputs

Selection must preserve the original candidate interval. Rendering needs a
possibly padded/refined interval, but the model must not imply that both spans
carry identical text when they do not.

## Expected changes

- Define a refined-selection value containing candidate/rank identity, scored
  interval, refined interval, padding, reasons, and refinement version.
- Validate finite ordered times against source duration using explicit
  tolerances where appropriate.
- Define closed reason codes for unchanged, word-aligned, pause-aligned,
  padded, clamped, rejected, or requires-rescore outcomes.
- Define a versioned material-change policy based on transcript membership,
  not guessed semantic similarity.
- Add serialization and invariant tests for valid and invalid intervals.

## Acceptance criteria

- Scored and refined intervals are both retained and cannot be confused by
  callers.
- Refined times are finite, non-negative, ordered, and no later than the probed
  source duration.
- Rank, candidate ID, score/checklist provenance, and source transcript indexes
  survive refinement unchanged.
- Material-change state is explicit and cannot be represented as both safe and
  requiring rescoring.
- The contract contains no FFmpeg or provider-specific types.

## Tests and validation

```bash
pytest tests/unit -k "refin and model"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not collapse the scored and render interval into one mutable candidate.
- Exact FFmpeg timestamp tolerance belongs to rendering tests, not this domain
  contract.
