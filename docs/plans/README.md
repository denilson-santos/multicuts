# Implementation Plans

## Current state

`multicuts` has completed the project bootstrap, domain foundation, local
source/media preflight, CLI foundation, `multisubs` transcription adapter, the
output-local transcript cache, semantic candidate generation, and deterministic
candidate evaluation, explainable heuristic scoring, and YouTube acquisition.
The integrated pipeline now renders selected clips, burns configured hard
subtitles by default, and publishes reusable final clip artifacts. The complete
run manifest and outcome summary remain package 016 work.

Packages 010–014 completed selection, semantic/hybrid scoring, boundary
refinement, and raw clip rendering. Package 015 completed source-derived
subtitles, final-geometry hard-subtitle rendering, and final clip persistence.
Package 016 is the remaining M3 completion work. M4 release hardening remains
later work.

## Status and priority

Package and task status use this vocabulary:

- `planned`: approved for the roadmap but not started;
- `in-progress`: active implementation exists on a delivery branch;
- `in-review`: implementation and validation are complete with an open PR;
- `blocked`: work cannot continue until a named dependency or open decision is
  resolved;
- `completed`: acceptance criteria and required validation have passed and the
  change has been integrated.

Priority indicates sequencing impact:

- `P0`: a foundation that blocks multiple downstream packages;
- `P1`: part of the first functional local intelligence/output path;
- `P2`: documented input or scoring breadth that can proceed independently of
  that path.

Status changes must update the package README and the relevant task files in the
same delivery. A package becomes `completed` only when all its tasks are
completed and its package-level completion criteria pass.

## Package index

| Package | Milestone | Status | Priority | Depends on | PRs | Expected outcome |
| --- | --- | --- | --- | --- | --- | --- |
| [001 Project bootstrap](001-project-bootstrap/) | M0 | completed | P0 | None | [#4](https://github.com/denilson-santos/multicuts/pull/4), [#5](https://github.com/denilson-santos/multicuts/pull/5), [#6](https://github.com/denilson-santos/multicuts/pull/6), [#7](https://github.com/denilson-santos/multicuts/pull/7) | Installable package, quality tooling, build checks, and CI |
| [002 Domain foundation](002-domain-foundation/) | M0 | completed | P0 | 001 | [#8](https://github.com/denilson-santos/multicuts/pull/8), [#9](https://github.com/denilson-santos/multicuts/pull/9), [#10](https://github.com/denilson-santos/multicuts/pull/10) | Typed configuration, errors, and the domain models required through transcription |
| [003 CLI and pipeline foundation](003-cli-pipeline-foundation/) | M0 | completed | P1 | 002 | [#13](https://github.com/denilson-santos/multicuts/pull/13), [#14](https://github.com/denilson-santos/multicuts/pull/14), [#19](https://github.com/denilson-santos/multicuts/pull/19) | Documented command surface, readable orchestration boundary, logging, and exit handling |
| [004 Local source and media](004-local-source-media/) | M1 | completed | P1 | 002 | [#11](https://github.com/denilson-santos/multicuts/pull/11), [#12](https://github.com/denilson-santos/multicuts/pull/12), [#15](https://github.com/denilson-santos/multicuts/pull/15) | Validated local input, stable source identity, and normalized media metadata |
| [005 Multisubs transcription](005-multisubs-transcription/) | M1 | completed | P1 | 002, 004 | [#16](https://github.com/denilson-santos/multicuts/pull/16), [#18](https://github.com/denilson-santos/multicuts/pull/18) | Public-API transcription adapter and normalized transcript |
| [006 Transcript cache](006-transcript-cache/) | M1 | completed | P1 | 005 | [#21](https://github.com/denilson-santos/multicuts/pull/21) | Safely persisted and reusable normalized transcripts |
| [007 Semantic candidates](007-semantic-candidates/) | M2 | completed | P1 | 006 | [#24](https://github.com/denilson-santos/multicuts/pull/24) | Deterministic semantic units and bounded candidate windows with stable identities |
| [008 Candidate evaluation](008-candidate-evaluation/) | M2 | completed | P1 | 007 | [#31](https://github.com/denilson-santos/multicuts/pull/31) | Traceable checklist outcomes, reusable deterministic features, and a bounded scoring shortlist |
| [009 Explainable heuristic scoring](009-explainable-heuristic-scoring/) | M2 | completed | P1 | 008 | [#33](https://github.com/denilson-santos/multicuts/pull/33) | Versioned, reproducible `0..100` heuristic scores with dimensions and penalties |
| [010 Ranking and selection](010-ranking-selection/) | M2 | completed | P1 | 009 | [#35](https://github.com/denilson-santos/multicuts/pull/35) | Deterministic non-redundant top-K selection honoring the score threshold |
| [011 YouTube acquisition](011-youtube-acquisition/) | M1 | completed | P2 | 003, 004, 006 | [#34](https://github.com/denilson-santos/multicuts/pull/34) | Supported YouTube URLs normalized to controlled local media and safe metadata |
| [012 Semantic and hybrid scoring](012-semantic-hybrid-scoring/) | M2 | completed | P2 | 008, 009 | [#36](https://github.com/denilson-santos/multicuts/pull/36) | Validated provider judgments, explainable hybrid composition, and honest fallback provenance |
| [013 Boundary refinement](013-boundary-refinement/) | M3 | completed | P1 | 010 | [#37](https://github.com/denilson-santos/multicuts/pull/37) | Clean source-bounded render intervals that preserve scored-content provenance |
| [014 Clip rendering](014-clip-rendering/) | M3 | completed | P1 | 004, 013 | [#38](https://github.com/denilson-santos/multicuts/pull/38) | Safe accurate `original` and center-cropped `9:16` raw clips |
| [015 Clip subtitles](015-clip-subtitles/) | M3 | completed | P1 | 005, 006, 013, 014 | [#39](https://github.com/denilson-santos/multicuts/pull/39), [#40](https://github.com/denilson-santos/multicuts/pull/40), [#41](https://github.com/denilson-santos/multicuts/pull/41) | Clip-local transcript reuse and public-API `multisubs` hard subtitles |
| [016 Run artifacts and end-to-end completion](016-run-artifacts/) | M3 | in-progress | P1 | 010, 011, 014, 015 | — | Complete per-clip metadata, run manifest, and honest final CLI outcomes |

Package 015 tasks 001–004 are integrated through PR #41. The package now
publishes validated hard-subtitled clips and reusable subtitle provenance;
package 016 owns the complete run manifest and final outcome summary.

## Recommended execution order

The main dependency path is:

```text
001 -> 002 -> 004 -> 005 -> 006 -> 007 -> 008 -> 009 -> 010
002 -> 003
003 + 004 + 006 -> 011 -> 016
008 + 009 -> 012
010 -> 013 -> 014 -> 015 -> 016
```

Packages 012–015 are complete. Package 016 is the remaining M3 work for a
traceable complete local run. Its schema task begins first, followed by safe
artifact publication, CLI outcome mapping, and end-to-end acceptance.

## Global implementation constraints

Every package must preserve these established decisions:

- Python remains `>=3.10,<3.14`.
- The application remains synchronous and processes one source per invocation.
- Domain code operates on project-owned models and does not import yt-dlp,
  FFmpeg command details, provider objects, or private `multisubs` modules.
- Expensive side effects stay at narrow acquisition, transcription, media, and
  artifact boundaries.
- Configuration and media are validated before transcription models are loaded.
- Local media stays local unless the user explicitly configures a remote
  provider; secrets never enter logs or artifacts.
- The source is transcribed at most once for each relevant transcription
  configuration.
- The default test suite is deterministic and requires no network, GPU, model
  download, YouTube access, remote scorer credentials, or FFmpeg.
- Use dataclasses for project value objects, `pathlib.Path` for paths, standard
  `logging` for diagnostics, pytest for tests, Ruff for formatting/linting, and
  Pyright for type checking.
- Use the Python standard-library `venv` module for the local development
  environment, stored in the repository root as `.venv/`; CI creates its own
  isolated environment and never depends on a developer's `.venv`.
- Introduce only modules with an immediate responsibility; do not add a DI
  container, repository layer, database, workflow engine, async pipeline, or
  generic cache framework.

## Deferred work

The following work is intentionally excluded from these packages:

- advanced yt-dlp cookie configuration and downloaded-source retention policy;
- multiple semantic-provider adapters, embedding-based diversity, and an
  unselected fully local semantic model;
- face tracking, smart reframing, manual crop offsets, and subtitle-preset
  design that duplicates `multisubs`;
- implementation/release work in the external `multisubs` repository; package
  015 consumes and contract-tests the required public capability once available;
- packaging/release hardening beyond the initial build and CI baseline.

## Shared open decisions

The source documents do not yet determine:

- the exact semantic-unit pause threshold and punctuation heuristics;
- the default candidate budget, including whether it scales with source
  duration;
- the exact heuristic mapping from deterministic features to scoring dimensions
  and penalty points;
- whether the suggested `0.60` temporal-overlap threshold should become the
  initial default;
- whether semantic near-duplicate detection should later use embeddings;
- advanced yt-dlp cookie behavior and downloaded-source retention policy;
- which supported public `multisubs` release/API will build styled subtitle
  artifacts from an existing clip-local transcript and target geometry;
- how required per-clip `title` and `summary` fields are derived without
  fabricating semantic-provider output;
- whether zero eligible clips is a successful completed run or a distinct
  non-error terminal outcome;
- whether reusable workspace/cache data ultimately moves from the implemented
  output-local layout to a global cache.

Each affected package identifies when the decision must be made. Implementers
must not silently turn an unresolved option into a permanent product contract.

## Source documents

- [Product requirements](../prd.md)
- [Architecture](../architecture.md)
- [Engineering conventions](../conventions.md)
- [Repository instructions](../../AGENTS.md)
