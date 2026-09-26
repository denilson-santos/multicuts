# Package 016: Run Artifacts and End-to-End Completion

| Field | Value |
| --- | --- |
| Milestone | M3 — Media output |
| Status | in-progress |
| Priority | P1 |
| Depends on | 010 Ranking and selection; 011 YouTube acquisition; 014 Clip rendering; 015 Clip subtitles |
| Unlocks | Complete M3 runs and M4 release hardening |
| PRs | [#42](https://github.com/denilson-santos/multicuts/pull/42), [#43](https://github.com/denilson-santos/multicuts/pull/43), [#44](https://github.com/denilson-santos/multicuts/pull/44) |

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
artifact module now publishes the complete final schema at `manifest.json`.

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
| [001 Define manifest and per-clip metadata contracts](001-define-artifact-contracts.md) | completed | P1 | Packages 010, 014; Task 015.001 | [#42](https://github.com/denilson-santos/multicuts/pull/42) | Versioned complete artifact schemas with safe provenance |
| [002 Collect and publish final artifacts safely](002-publish-final-artifacts.md) | completed | P1 | 001 | [#43](https://github.com/denilson-santos/multicuts/pull/43) | Atomic clip metadata and manifest publication from real stage results |
| [003 Complete pipeline and CLI outcome semantics](003-complete-pipeline-and-cli.md) | completed | P1 | 002 | [#44](https://github.com/denilson-santos/multicuts/pull/44) | Honest end-to-end success, zero-selection, partial, and failure behavior |
| [004 Verify local and YouTube end-to-end acceptance](004-verify-end-to-end-acceptance.md) | in-progress | P1 | 003; Package 011 | — | Evidence for M3/MVP acceptance without weakening hermetic defaults |

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

- Task 001 derives title and summary deterministically from candidate
  transcript excerpts. A future editorial title generator needs a separate
  product decision.
- A zero-selection run publishes its manifest with a distinct outcome and exits
  successfully. A partial or all-render-failed run publishes the corresponding
  outcome and exits with the rendering failure code; CLI output names the state.
- The public multisubs contract required by package 015 and package 016's
  artifact publication, and CLI outcomes are integrated; end-to-end acceptance
  is in progress.
- M4 remains responsible for broader interruption cleanup, corrupted-cache
  hardening, packaging, and reproducible release checks.
