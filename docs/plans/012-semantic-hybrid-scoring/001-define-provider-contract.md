# Task 012.001: Define the Semantic Provider Contract and Configuration

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P2 |
| Depends on | Packages 008 Candidate evaluation; 009 Explainable heuristic scoring |
| PR | — |

## Objective

Resolve the initial provider decision and define the smallest project-owned
request, result, configuration, and provenance contracts needed for semantic
judgments.

## Context and inputs

The PRD requires a provider boundary and recommends hybrid scoring. Decision
D-013 selects OpenAI with `gpt-6-luna` at reasoning effort `max` and defers a
fully local semantic model. Package 009 already owns score dimensions,
composition, and penalties, so this task must not create a second scoring
schema.

## Expected changes

- Record the selected initial provider/model and credential/configuration
  expectations in the package and existing user-facing documentation.
- Define a project-owned semantic request containing candidate identity, minimum
  text, and only the surrounding context justified by the prompt.
- Define normalized semantic judgments compatible with package 009 score
  contracts, plus provider/model/prompt provenance.
- Define scorer modes and validation without embedding secrets in configuration
  artifacts, representations, or logs.
- Define retryable versus deterministic provider failures and explicit fallback
  policy configuration.

## Acceptance criteria

- One initial provider/model boundary is named before its adapter is built.
- Domain/scoring modules do not depend on provider SDK request or response
  types.
- The request excludes raw video/audio and makes surrounding-text limits
  explicit.
- Credentials are obtained through a documented secret-bearing mechanism and
  are excluded from persisted configuration and logs.
- Provider/model/prompt version and fallback use can be represented without
  changing the package 009 final-score schema.
- Unsupported scorer/provider values fail configuration validation clearly.

## Tests and validation

```bash
pytest tests/unit -k "config and scor"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not silently select a provider merely because its SDK is convenient.
- Do not introduce a provider registry, generic HTTP framework, or multiple
  adapters in anticipation of future choices.
