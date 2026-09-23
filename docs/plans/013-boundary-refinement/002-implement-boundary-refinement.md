# Task 013.002: Implement Deterministic Boundary Refinement

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 013.001 Define refined interval contracts |
| PR | — |

## Objective

Choose cleaner nearby cut points from existing transcript timing and apply
bounded padding without changing candidate selection.

## Context and inputs

The algorithm runs only for selected candidates. It may inspect words,
segments, punctuation, and measured pauses within a small configured
neighborhood but may not perform new ASR or audio zero-crossing analysis.

## Expected changes

- Implement pure helpers for nearby first-word, last-word, segment, and pause
  boundary candidates.
- Define and version the search radius and deterministic tie order.
- Apply configured pre-roll/post-roll after choosing semantic cut points.
- Clamp to `0` and source duration while preserving a positive valid interval.
- Fall back conservatively when word timing is absent or unsafe.
- Add table-driven tests for pauses, punctuation, source edges, overlapping
  segments, and incomplete timing.

## Acceptance criteria

- Refinement examines no timing outside the configured neighborhood.
- The same transcript, selected candidate, media duration, and configuration
  always produce the same interval and reason codes.
- Default padding is explicit and source-edge clamping is tested.
- No output cuts through a timed word when a safe nearby boundary is available
  under the configured policy.
- Missing timing produces a documented conservative result without fabricated
  word boundaries.
- The implementation performs no filesystem, provider, or FFmpeg side effects.

## Tests and validation

```bash
pytest tests/unit -k "boundary or refin"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Sentence punctuation and pauses are imperfect semantic proxies; the tie order
  and thresholds must be versioned implementation choices.
- Do not move boundaries far enough to turn refinement into candidate
  regeneration.
