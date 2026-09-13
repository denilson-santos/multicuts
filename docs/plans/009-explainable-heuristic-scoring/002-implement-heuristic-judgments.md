# Task 009.002: Implement Heuristic Judgments

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 009.001 Define versioned score contracts |
| PR | — |

## Objective

Map deterministic features and checklist evidence into documented dimension
judgments and evidence-completeness confidence.

## Context and inputs

The local heuristic mode is the CLI default and must work without a remote
semantic provider. Its limitations must remain visible: it evaluates only
signals that package 008 actually computed.

## Expected changes

- Define versioned, bounded mappings from relevant features/rules to each
  scoring dimension.
- Produce a concise explanation tied to observed evidence and unknowns.
- Define heuristic confidence from evidence availability/quality rather than
  provider certainty or predicted virality.
- Keep weights and deterministic penalties outside the judgment calculation.
- Preserve unknown evidence rather than substituting a favorable midpoint
  silently.
- Add invariant and monotonicity tests for each mapping where meaningful.

## Acceptance criteria

- Fixed feature/checklist inputs produce identical dimension values, confidence,
  and explanation.
- Every dimension value names a documented deterministic source or explicit
  neutral/unknown policy.
- Improving a clearly positive input cannot lower its mapped dimension unless a
  named counter-signal applies.
- No output carries a semantic provider/model/prompt identifier.
- Explanations do not claim that an LLM understood the content.

## Tests and validation

```bash
pytest tests/unit -k "heuristic and scoring"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Some semantic dimensions will be coarse without a provider. Keep the mapping
  reviewable and versioned instead of adding an unapproved NLP dependency.
- Heuristic mappings should be easy to replace after evaluation data exists.
