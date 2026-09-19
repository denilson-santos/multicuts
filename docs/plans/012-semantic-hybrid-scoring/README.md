# Package 012: Semantic and Hybrid Scoring

| Field | Value |
| --- | --- |
| Milestone | M2 — Intelligence |
| Status | planned |
| Priority | P2 |
| Depends on | 008 Candidate evaluation; 009 Explainable heuristic scoring |
| Unlocks | Configured semantic judgments and hybrid score provenance |
| PRs | — |

## Objective and expected outcome

Add one explicitly configured semantic scoring provider behind a narrow adapter,
validate its structured judgments, and combine them with the deterministic
features, composition rules, and penalties established by packages 008–009.
Provider failure remains visible and may use the documented heuristic fallback
without fabricating a semantic result.

## Context

FR-SCORE-006–009 and decision D-006 establish hybrid scoring as the MVP
direction, but the PRD does not choose a provider/model or require a fully local
semantic mode. This package therefore includes an explicit provider decision
gate and must not make `hybrid` appear operational before a real, validated
adapter is configured.

## Included scope

- project-owned semantic request/result contracts and scorer configuration;
- selection and documentation of one initial provider/model boundary;
- minimum-text/context requests with validated structured responses;
- bounded retry classification and candidate-level failure recording;
- hybrid composition using the existing project-owned weights and penalties;
- explicit heuristic fallback provenance when configured;
- provider/model/prompt-aware score persistence and reuse;
- hermetic adapter, fallback, cache, and pipeline tests.

## Out of scope

- sending raw video or audio to the scoring provider;
- multiple interchangeable provider implementations or a plugin registry;
- embeddings for semantic deduplication;
- inventing provider judgments after timeouts or malformed responses;
- changing ranking, boundary refinement, rendering, or subtitle behavior;
- deciding that remote scoring is mandatory for the local offline path.

## Requirements and established decisions

- [PRD: scoring](../../prd.md#97-scoring)
- [PRD: privacy](../../prd.md#13-privacy)
- [Architecture: scoring adapter](../../architecture.md#73-adaptersscoringpy)
- [Architecture: scoring architecture](../../architecture.md#9-scoring-architecture)
- [Architecture: scoring cache](../../architecture.md#scoring-cache-key)
- [Conventions: scoring](../../conventions.md#16-scoring-conventions)

## Likely components

- semantic provenance/config additions to `src/multicuts/models.py` and
  `src/multicuts/config.py`
- `src/multicuts/adapters/scoring.py`
- hybrid orchestration near the project-owned scoring modules
- provider-aware persistence in `src/multicuts/artifacts.py`
- scorer routing in `src/multicuts/pipeline.py`
- hermetic provider payload fixtures and `tests/unit/`

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define the semantic provider contract and configuration](001-define-provider-contract.md) | planned | P2 | Packages 008, 009 | — | Explicit provider choice, minimal requests, and project-owned validated judgments |
| [002 Implement the initial semantic adapter](002-implement-semantic-adapter.md) | planned | P2 | 001 | — | Bounded external calls normalized without provider leakage |
| [003 Compose hybrid results and fallback behavior](003-compose-hybrid-results.md) | planned | P2 | 002 | — | Explainable hybrid scores and honest heuristic fallback provenance |
| [004 Persist and integrate hybrid scoring](004-persist-and-integrate-hybrid-scoring.md) | planned | P2 | 003 | — | Cache-safe, configured hybrid execution in the synchronous pipeline |

## Suggested task sequence

Resolve and document the single initial provider/model and its configuration
contract before adapter code. Normalize and validate provider output next, then
compose hybrid results through existing project-owned rules. Add cache identity
and pipeline routing only after the failure and fallback semantics are stable.

## Completion criteria

- A configured semantic scorer receives only the minimum candidate text and
  context needed; raw media is never sent by default.
- Provider output is converted immediately to validated project-owned values,
  including all required dimensions, confidence, reason, and provenance.
- Retries are bounded and limited to retryable failures; malformed structured
  responses are not retried indefinitely or converted into invented results.
- Hybrid composition reuses the versioned weights, penalties, and `0..100`
  validation from package 009.
- A fallback result is distinguishable from a semantic result and retains the
  provider error as a safe warning.
- Provider/model/prompt changes invalidate semantic scoring reuse without
  invalidating transcription, deterministic features, or rendering artifacts.
- The default suite uses fakes/fixtures and requires no network or credentials.

## Risks, assumptions, and open questions

- The initial semantic provider/model and whether a fully local semantic mode
  is required remain open PRD questions. Task 001 is a decision gate; no adapter
  should be implemented until that choice is recorded in an existing source
  document or the package plan.
- Provider schemas and model behavior can change. Contract tests should cover
  the narrow normalized response rather than expose an SDK response throughout
  the application.
- The package assumes package 009 owns final score arithmetic. Provider output
  supplies semantic judgments, not an authoritative opaque final score.
- This package can proceed independently of packages 010 and 013–016 and does
  not block the first heuristic local-rendering path.
