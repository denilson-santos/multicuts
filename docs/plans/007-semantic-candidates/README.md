# Package 007: Semantic Candidates

| Field | Value |
| --- | --- |
| Milestone | M2 — Intelligence |
| Status | planned |
| Priority | P1 |
| Depends on | 006 Transcript cache |
| Unlocks | 008 Candidate evaluation |
| PRs | — |

## Objective and expected outcome

Transform one normalized transcript into deterministic semantic units and a
bounded set of adjacent candidate windows that respect configured duration
limits. Completion gives each candidate a stable, versioned identity and enough
clip-local text/timing for later evaluation without another ASR pass.

## Context

Candidate generation is the first unimplemented stage after the transcript
cache. FR-CAN-001–005 require meaningful transcript boundaries, non-exhaustive
window construction, duration constraints, limited boundary expansion, and
stable IDs. The generator is pure project-owned domain logic and must not call
an LLM or depend on provider objects.

## Included scope

- candidate and semantic-unit value objects required by this package;
- deterministic semantic units from normalized segments, punctuation, pauses,
  and available word timings;
- adjacent-unit windows within `min_duration` and `max_duration`;
- narrowly bounded expansion to a natural timed boundary when it remains within
  the hard maximum;
- stable candidate IDs derived from source fingerprint, interval, and generator
  version;
- synchronous pipeline integration after transcript loading;
- hermetic unit and golden-fixture tests.

## Out of scope

- checklist rules, deterministic scoring features, or candidate-budget pruning;
- semantic topic detection that requires a model or provider;
- score composition, ranking, overlap deduplication, or rendering;
- candidate/scoring artifact persistence beyond data needed by the pipeline;
- inventing timestamps for untimed transcript content.

## Requirements and established decisions

- [PRD: candidate generation](../../prd.md#95-candidate-generation)
- [PRD: single transcription](../../prd.md#p-006--single-transcription-multiple-derivatives)
- [Architecture: candidate generator](../../architecture.md#candidatesgeneratorpy)
- [Architecture: models](../../architecture.md#modelspy)
- [Conventions: data models](../../conventions.md#9-data-models)

## Likely components

- candidate-related additions to `src/multicuts/models.py`
- `src/multicuts/candidates/generator.py`
- candidate-stage orchestration in `src/multicuts/pipeline.py`
- small normalized transcript fixtures under `tests/fixtures/`
- `tests/unit/`

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define candidate contracts and identity](001-define-candidate-contracts.md) | planned | P1 | Package 006 | — | Typed candidate intervals, text, provenance, and stable versioned IDs |
| [002 Build semantic units](002-build-semantic-units.md) | planned | P1 | 001 | — | Deterministic timed units from available transcript boundaries |
| [003 Generate bounded candidate windows](003-generate-candidate-windows.md) | planned | P1 | 002 | — | Non-exhaustive adjacent-unit windows within configured limits |
| [004 Integrate the candidate stage](004-integrate-candidate-stage.md) | planned | P1 | 003 | — | Pipeline reaches candidate generation and reports an honest downstream stop |

## Suggested task sequence

Implement 007.001–007.003 in order so identity and boundary behavior are stable
before orchestration depends on them. Integrate the completed pure generator in
007.004; do not merge a production pipeline path that emits placeholder
candidates while the algorithm is incomplete.

## Completion criteria

- Candidate output is deterministic for the same transcript, source fingerprint,
  duration configuration, and generator version.
- Every emitted candidate has finite ordered timestamps, nonempty normalized
  text, and a stable ID containing no raw provider object.
- All candidates satisfy configured hard duration limits after any expansion.
- Window generation grows from meaningful boundaries rather than arbitrary
  timestamp enumeration.
- Untimed or partially timed transcript data is handled explicitly and no
  timestamp is fabricated.
- The pipeline passes a cache-loaded or newly transcribed `Transcript` into the
  same generator path and still avoids repeated ASR.
- Focused tests and the repository's standard non-integration checks pass.

## Risks, assumptions, and open questions

- The PRD names pause and punctuation signals but does not define exact
  thresholds. Task 002 must record small versioned initial heuristics and cover
  them with fixtures; changing their meaning requires a generator-version bump.
- Topic-change detection is only included when already represented in normalized
  transcript data. Adding a semantic model is not authorized by this package.
- Transcript segments may have timing while some words do not. The generator
  must prefer real boundaries and reject unusable spans rather than interpolate
  fictional word times.
- The PRD allows boundary expansion but does not require a specific padding
  amount. Task 003 should make any initial bound explicit and keep it subordinate
  to `max_duration`.
