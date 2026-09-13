# Task 007.003: Generate Bounded Candidate Windows

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 007.002 Build semantic units |
| PR | — |

## Objective

Combine adjacent semantic units into a bounded, deterministic set of candidate
windows that satisfies configured duration limits.

## Context and inputs

FR-CAN-002–004 and NFR-PERF-005 prohibit naive enumeration of arbitrary
timestamp windows. The initial preferred duration is 25–45 seconds, while the
hard defaults remain 15–60 seconds through `RunConfig`.

## Expected changes

- Generate only contiguous windows anchored to semantic-unit boundaries.
- Enforce `min_duration <= duration <= max_duration` for every result.
- Prefer windows in the documented 25–45 second range without treating it as a
  new hard validity constraint.
- Apply only small natural-boundary expansion that remains within the hard
  maximum.
- Deduplicate identical intervals before assigning stable candidate IDs.
- Add golden fixtures for short sources, exact boundaries, source-end clipping,
  sparse units, and repeated text.

## Acceptance criteria

- No emitted candidate violates configured duration bounds or source duration.
- Candidate ordering and identities are stable across repeated runs.
- The algorithm operates on adjacent semantic units and does not enumerate every
  possible timestamp pair.
- Exact minimum/maximum boundaries and floating-point comparisons have explicit
  tests.
- A transcript with no valid window returns an empty result without fabricating
  content or raising an unrelated provider error.

## Tests and validation

```bash
pytest tests/unit -k "candidate_window"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Candidate-budget pruning before expensive scoring belongs to package 008.
- The preferred-range ordering rule must remain explainable and deterministic;
  it is not itself the final ranking algorithm.

## Implementation decision

Version `1` considers every semantic-unit start but selects at most one nearest
endpoint for each of the configured minimum, preferred 25/35/45-second targets,
and configured maximum. This emits at most five windows per unit start instead
of enumerating every contiguous combination. Complete unit boundaries provide
the natural expansion, so no separate timestamp padding is added. Preferred-
range windows sort by distance from 35 seconds, then source interval and
candidate ID. The candidate budget sent to semantic scoring remains package 008.
