# Task 010.002: Implement Overlap and Redundancy Policies

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 010.001 Define ranking primitives and order |
| PR | [#35](https://github.com/denilson-santos/multicuts/pull/35) |

## Objective

Provide pure, explainable redundancy checks for temporal overlap and an
extensible non-temporal diversity boundary.

## Context and inputs

FR-RANK-002 defines temporal overlap as intersection duration divided by the
shorter candidate duration and suggests `0.60`. FR-RANK-004 requires the design
not to assume time overlap is the only redundancy form.

## Expected changes

- Implement the exact temporal-overlap ratio for valid intervals.
- Apply an explicit configurable threshold with well-defined inclusive/exclusive
  semantics.
- Return stable redundancy reason/evidence values rather than a bare boolean.
- Define a small callable/protocol boundary for non-temporal redundancy.
- If deterministic normalized-text similarity is included, document its
  normalization, threshold, and limitations.
- Add contained, disjoint, boundary-touching, identical, and floating-point
  threshold tests.

## Acceptance criteria

- Disjoint/boundary-touching intervals have zero overlap and identical intervals
  have ratio one.
- Contained intervals divide by the shorter duration as documented.
- Threshold equality behavior is explicit and tested.
- Redundancy reasons identify temporal versus text/policy suppression.
- The default implementation requires no embeddings, network, or external
  provider but can be replaced without changing selection arithmetic.

## Tests and validation

```bash
pytest tests/unit -k "overlap or redundancy"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- A naive text similarity rule can over-suppress recurring legitimate topics.
  Keep it conservative and independently configurable, or defer it while
  preserving the boundary.
- Do not hide overlap as a score penalty; it is selection evidence.
