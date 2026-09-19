# Package 016: Run Artifacts and End-to-End Completion

| Field | Value |
| --- | --- |
| Milestone | M3 — Media output |
| Status | planned |
| Priority | P1 |
| Depends on | 010 Ranking and selection; 011 YouTube acquisition; 014 Clip rendering; 015 Clip subtitles |
| Unlocks | Complete M3 runs and M4 release hardening |
| PRs | — |

## Objective and expected outcome

Publish versioned per-clip metadata and one complete run manifest, then make the
CLI report honest end-to-end outcomes for local and supported YouTube sources.
Completion turns validated final media into a traceable product artifact and
closes the M3 pipeline without hiding zero-selection, partial failure, or
provider fallback states.

## Context

FR-ART-001–003 make artifacts part of the product contract, not incidental
debug output. AC-001–014 require final clips, score/checklist details, geometry,
subtitle/template provenance, single-ASR reuse, and failed-render safety. The
current artifact module reserves `manifest.json`; this package defines and
publishes its complete final schema.

## Included scope

- versioned run-manifest and per-clip metadata contracts;
- all required source, config, version, stage, clip, timing, warning, score, and
  provenance fields;
- safe local/YouTube source references with no credentials;
- atomic JSON publication paired with validated final media;
- explicit completed, zero-selection, partial-failure, and failed-run semantics;
- concise CLI completion summary and final output paths;
- hermetic local end-to-end tests and opt-in external-tool/source acceptance
  coverage.

## Out of scope

- dashboards, databases, telemetry services, queues, or run APIs;
- new title/hook generation features not required by the metadata contract;
- broad interruption/cleanup, cache-corruption, packaging, or release hardening;
- changing candidate, score, selection, rendering, or subtitle algorithms;
- persisting secrets, cookies, authorization data, or raw provider payloads.

## Requirements and established decisions

- [PRD: artifacts](../../prd.md#911-artifacts)
- [PRD: MVP acceptance criteria](../../prd.md#20-mvp-acceptance-criteria)
- [Architecture: workspace and artifacts](../../architecture.md#12-workspace-and-artifacts)
- [Architecture: state and side effects](../../architecture.md#16-state-and-side-effects)
- [Architecture: error handling](../../architecture.md#14-error-handling)
- [Conventions: filesystem](../../conventions.md#12-filesystem-conventions)

## Likely components

- manifest/per-clip values in `src/multicuts/models.py`
- final JSON serialization/publication in `src/multicuts/artifacts.py`
- stage result/timing/warning aggregation in `src/multicuts/pipeline.py`
- final outcome/summary mapping in `src/multicuts/cli.py`
- end-to-end fixtures across `tests/unit/` and `tests/integration/`

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define manifest and per-clip metadata contracts](001-define-artifact-contracts.md) | planned | P1 | Packages 010, 014; Task 015.001 | — | Versioned complete artifact schemas with safe provenance |
| [002 Collect and publish final artifacts safely](002-publish-final-artifacts.md) | planned | P1 | 001 | — | Atomic clip metadata and manifest publication from real stage results |
| [003 Complete pipeline and CLI outcome semantics](003-complete-pipeline-and-cli.md) | planned | P1 | 002 | — | Honest end-to-end success, zero-selection, partial, and failure behavior |
| [004 Verify local and YouTube end-to-end acceptance](004-verify-end-to-end-acceptance.md) | planned | P1 | 003; Package 011 | — | Evidence for M3/MVP acceptance without weakening hermetic defaults |

## Suggested task sequence

Define stable schemas and resolve metadata ambiguities before serialization.
Aggregate real stage results and publish atomically next. Finalize CLI semantics
only after artifact outcomes exist, then validate the same downstream path for
local and YouTube sources with hermetic boundaries plus marked live-tool tests.

## Completion criteria

- Every completed clip has validated media and a JSON file containing every
  FR-ART-002 field with scored versus rendered intervals clearly distinguished.
- Every concluded run publishes one versioned manifest containing all
  FR-ART-001 fields and applicable FR-ART-003 provenance, warnings, and timings.
- Manifests identify actual heuristic, semantic-hybrid, or fallback behavior
  without inventing provider/model provenance.
- Local and supported YouTube sources share the same post-acquisition flow and
  emit safe source provenance.
- Zero eligible clips and partial clip failures have explicit deterministic
  outcomes; neither is mislabeled as an all-clips success.
- Final JSON/media files are never published partially or silently overwritten.
- End-to-end evidence covers single ASR use, cache reuse, original/vertical
  geometry, subtitle-enabled behavior, and final template provenance.

## Risks, assumptions, and open questions

- FR-ART-002 requires `title` and `summary` but does not define their derivation;
  PRD question 8 also leaves title/hook suggestions open. Task 001 must record a
  supported deterministic derivation or an explicit producer dependency before
  implementation, rather than fabricate semantic-provider output.
- The PRD does not explicitly define whether a zero-selection run is a
  successful completed run or a distinct non-error outcome. Task 003 must decide
  and document CLI/manifest semantics while preserving the domain distinction.
- Package completion depends on the public `multisubs` blocker recorded in
  015.002. Schema work may start earlier, but subtitle-enabled M3 acceptance
  cannot pass until that blocker is cleared.
- M4 remains responsible for broader interruption cleanup, corrupted-cache
  hardening, packaging, and reproducible release checks.
