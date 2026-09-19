# Task 016.001: Define Manifest and Per-Clip Metadata Contracts

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | Packages 010 Ranking and selection; 014 Clip rendering; Task 015.001 Derive clip-local transcripts |
| PR | — |

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
