# Task 016.001: Define Manifest and Per-Clip Metadata Contracts

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | Packages 010 Ranking and selection; 014 Clip rendering; Task 015.001 Derive clip-local transcripts |
| PR | [#42](https://github.com/denilson-santos/multicuts/pull/42) |

## Objective

Define versioned project-owned schemas for the final run manifest and per-clip
metadata, including every required field and safe provenance.

## Context and inputs

Final artifacts aggregate normalized outputs from all stages. They must remain
smaller and more stable than external-provider payloads and must distinguish
original candidate, refined render, and clip-local time domains.

## Expected changes

- Define typed run manifest, source/config/version/stage summary, clip metadata,
  timing, warning, and final outcome values.
- Map all FR-ART-001/002/003 fields to existing project-owned stage results.
- Define schema versions and JSON-compatible representations for paths, times,
  enums, optional provider/template provenance, and failure/fallback states.
- Resolve and document the source of required clip `title` and `summary` fields
  without inventing a semantic-provider result.
- Define safe local/remote source references and explicit secret exclusions.
- Add invariant and serialization tests, including backward-incompatible schema
  rejection behavior.

## Acceptance criteria

- Every required PRD field has one documented typed source and time domain.
- Candidate `source_start/source_end` and refined `render_start/render_end` are
  preserved separately.
- Heuristic, semantic-hybrid, and fallback provenance are representable without
  false provider/model values.
- Subtitle-disabled and subtitle-enabled clips both have explicit render/template
  states.
- Title/summary derivation or dependency is decided and testable before the
  schema is considered complete.
- No raw SDK/yt-dlp/FFmpeg payload or secret-bearing value enters the schema.

## Schema decisions

Schema version 1 is represented by project-owned values in
src/multicuts/final_artifacts.py. Both final JSON documents carry
schema_version=1; readers reject unknown versions and incompatible fields.
Serialization uses JSON values, finite numbers, string enum values, and
workspace-relative POSIX artifact paths.

| Artifact field | Typed source and time domain |
| --- | --- |
| Manifest run_id, created_at, outcome | Final run identity, timezone-aware creation time, and explicit outcome |
| Manifest source, source_fingerprint | Normalized AcquiredSource, with local fingerprint reference or canonical YouTube video URL |
| Manifest config, versions | Safe RunConfig snapshot and observed tool/package versions |
| Manifest transcription, candidate_generation, scoring, selection | Actual normalized stage summaries; score counts distinguish heuristic, hybrid, and fallback outputs |
| Manifest clips, timings, warnings | Published or failed clip references, observed stage durations, and safe warning codes |
| Clip id, rank, source_start/end | SelectedCandidate candidate ID, rank, and original scored source interval |
| Clip render_start/end, duration | RefinedSelection source interval and measured rendered media duration |
| Clip candidate_text, title, summary | Scored candidate text; title is its first sentence, capped at 80 characters, and summary is a whitespace-normalized excerpt capped at 280 characters |
| Clip transcript | Source-derived clip-local transcript for the refined render interval; it may be empty for a silent unsubtitled clip |
| Clip score, confidence, dimension_scores, penalties, reason | ScoreResult; the numeric score and provider provenance remain in the nested score record, with the listed details repeated as consistent top-level fields |
| Clip checklist | CandidateEvaluation.checklist |
| Clip render_config, output_path | Final clip geometry and observed subtitle template provenance; relative output path |

Title and summary are deterministic text excerpts, not generated editorial claims.
The subtitle-disabled render state has null template provenance. Provider/model
fields are present only for scores that actually used the semantic provider;
heuristic fallback scores retain null provider/model fields. Local paths and
user-provided URL query strings do not enter source references.

Task 002 will construct and publish these values from stage results. Task 003
will map outcome values to CLI behavior and exit codes.

## Tests and validation

```bash
pytest tests/unit -k "manifest or clip_metadata"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not make every intermediate provider field part of the public artifact
  contract merely because it is available.
- Schema migration utilities are unnecessary until a concrete prior final
  schema must be supported; version rejection is sufficient for the MVP.
