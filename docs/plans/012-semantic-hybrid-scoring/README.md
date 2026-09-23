# Package 012: Semantic and Hybrid Scoring

| Field | Value |
| --- | --- |
| Milestone | M2 — Intelligence |
| Status | in-progress |
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

FR-SCORE-006–009 and decisions D-006 and D-013 establish hybrid scoring through
an optional OpenAI boundary while preserving the local heuristic route. This
package makes `hybrid` operational only when its real adapter and credential are
configured.

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
| [001 Define the semantic provider contract and configuration](001-define-provider-contract.md) | in-progress | P2 | Packages 008, 009 | — | Explicit provider choice, minimal requests, and project-owned validated judgments |
| [002 Implement the initial semantic adapter](002-implement-semantic-adapter.md) | in-progress | P2 | 001 | — | Bounded external calls normalized without provider leakage |
| [003 Compose hybrid results and fallback behavior](003-compose-hybrid-results.md) | in-progress | P2 | 002 | — | Explainable hybrid scores and honest heuristic fallback provenance |
| [004 Persist and integrate hybrid scoring](004-persist-and-integrate-hybrid-scoring.md) | in-progress | P2 | 003 | — | Cache-safe, configured hybrid execution in the synchronous pipeline |

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

- Provider schemas and model behavior can change. Contract tests should cover
  the narrow normalized response rather than expose an SDK response throughout
  the application.
- The package assumes package 009 owns final score arithmetic. Provider output
  supplies semantic judgments, not an authoritative opaque final score.
- This package can proceed independently of packages 010 and 013–016 and does
  not block the first heuristic local-rendering path.

## Implementation decisions

- The initial provider is OpenAI through the Responses API. The default semantic
  model is `gpt-6-luna` with reasoning effort `max`.
- Hybrid scoring is opt-in; heuristic scoring remains the default fully local
  path. A fully local semantic model is deferred beyond the MVP.
- Requests contain candidate text, derived features, and at most 500 characters
  of transcript context on each side. Raw media is never sent and responses use
  `store=false`.
- OpenAI support is installed through the optional `openai` dependency extra;
  credentials come only from `OPENAI_API_KEY`.
- Semantic dimensions feed the established project-owned weights, followed by
  the existing deterministic penalties exactly once.
- Provider failures are persisted per candidate. The default explicit fallback
  is heuristic scoring; `none` omits the failed candidate without fabricating a
  semantic result.
