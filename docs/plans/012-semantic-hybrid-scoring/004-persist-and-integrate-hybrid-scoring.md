# Task 012.004: Persist and Integrate Hybrid Scoring

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P2 |
| Depends on | 012.003 Compose hybrid results and fallback behavior |
| PR | [#36](https://github.com/denilson-santos/multicuts/pull/36) |

## Objective

Persist provider-aware score artifacts and make the configured hybrid mode
available through the synchronous CLI/pipeline path.

## Context and inputs

Semantic score reuse must include candidate identity, scoring algorithm,
weights/thresholds, provider/model, and prompt version. It must remain
independent of output geometry and subtitle styling.

## Expected changes

- Extend stage-specific score artifacts with semantic judgments, mode,
  provider/model/prompt provenance, fallback state, and safe warnings.
- Key reuse by every scoring-relevant input and reject malformed or mismatched
  cached results.
- Route the configured hybrid scorer through the existing candidate shortlist
  and ranking handoff.
- Preserve the fully local heuristic route when selected or used as configured
  fallback.
- Add pipeline tests for cache hit/miss, partial provider failure, fallback, and
  missing credential/configuration behavior.

## Acceptance criteria

- An exact compatible semantic result can be reused without another provider
  call.
- Provider, model, prompt, hybrid algorithm, weight, or threshold changes
  invalidate scoring reuse.
- Geometry, subtitle template, and rendering options do not invalidate score
  artifacts.
- Missing credentials fail before provider calls and never appear in artifacts
  or logs.
- Ranking receives the same project-owned scored-candidate contract for
  heuristic, semantic-hybrid, and fallback results.
- The non-integration suite performs no network calls.

## Tests and validation

```bash
pytest tests/unit -k "scoring and (artifact or pipeline or cache)"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not generalize the score cache into a cross-stage cache framework.
- Integration tests against the chosen provider remain opt-in and must use
  explicit test credentials and bounded cost.
