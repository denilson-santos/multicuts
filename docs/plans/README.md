# Initial Implementation Plans

## Current state

`multicuts` has completed the project bootstrap, domain foundation, and local
source/media preflight. The CLI and synchronous pipeline boundary exist, but the
production pipeline deliberately stops after media probing until normalized
transcription and artifact publication are integrated. CLI diagnostics and the
`multisubs` normalization/contract work are in progress; transcript caching is
planned.

These packages cover Milestone 0 and the local-source core of Milestone 1. They
stop once a normalized transcript can be persisted and reused. Later planning
will cover YouTube acquisition, candidate generation, scoring, ranking,
rendering, the complete run manifest, and release hardening.

## Status and priority

Package and task status use this vocabulary:

- `planned`: approved for the roadmap but not started;
- `in-progress`: active implementation exists on a delivery branch;
- `blocked`: work cannot continue until a named dependency or open decision is
  resolved;
- `completed`: acceptance criteria and required validation have passed and the
  change has been integrated.

Priority indicates sequencing impact:

- `P0`: a foundation that blocks multiple downstream packages;
- `P1`: part of the first functional local transcription path.

Status changes must update the package README and the relevant task files in the
same delivery. A package becomes `completed` only when all its tasks are
completed and its package-level completion criteria pass.

## Package index

| Package | Milestone | Status | Priority | Depends on | PRs | Expected outcome |
| --- | --- | --- | --- | --- | --- | --- |
| [001 Project bootstrap](001-project-bootstrap/) | M0 | completed | P0 | None | [#4](https://github.com/denilson-santos/multicuts/pull/4), [#5](https://github.com/denilson-santos/multicuts/pull/5), [#6](https://github.com/denilson-santos/multicuts/pull/6), [#7](https://github.com/denilson-santos/multicuts/pull/7) | Installable package, quality tooling, build checks, and CI |
| [002 Domain foundation](002-domain-foundation/) | M0 | completed | P0 | 001 | [#8](https://github.com/denilson-santos/multicuts/pull/8), [#9](https://github.com/denilson-santos/multicuts/pull/9), [#10](https://github.com/denilson-santos/multicuts/pull/10) | Typed configuration, errors, and the domain models required through transcription |
| [003 CLI and pipeline foundation](003-cli-pipeline-foundation/) | M0 | in-progress | P1 | 002 | [#13](https://github.com/denilson-santos/multicuts/pull/13), [#14](https://github.com/denilson-santos/multicuts/pull/14); current: — | Documented command surface, readable orchestration boundary, logging, and exit handling |
| [004 Local source and media](004-local-source-media/) | M1 | completed | P1 | 002 | [#11](https://github.com/denilson-santos/multicuts/pull/11), [#12](https://github.com/denilson-santos/multicuts/pull/12), [#15](https://github.com/denilson-santos/multicuts/pull/15) | Validated local input, stable source identity, and normalized media metadata |
| [005 Multisubs transcription](005-multisubs-transcription/) | M1 | in-progress | P1 | 002, 004 | [#16](https://github.com/denilson-santos/multicuts/pull/16); current: — | Public-API transcription adapter and normalized transcript |
| [006 Transcript cache](006-transcript-cache/) | M1 | planned | P1 | 005 | — | Safely persisted and reusable normalized transcripts |

## Recommended execution order

The main dependency path is:

```text
001 -> 002 -> 004 -> 005 -> 006
              |
              +---- 003
```

Package 003 and package 004 may proceed independently after package 002. When
they are implemented concurrently, they must agree on the `RunConfig`,
`AcquiredSource`, and `MediaInfo` contracts established by package 002.

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

- YouTube acquisition and advanced yt-dlp configuration;
- semantic-unit and candidate generation;
- filters, deterministic features, scoring providers, and ranking/deduplication;
- boundary refinement, FFmpeg cutting, aspect-ratio conversion, and subtitles;
- per-clip metadata and the complete run manifest;
- the missing public `multisubs` contract for building ASS from an existing
  clip-local transcript;
- packaging/release hardening beyond the initial build and CI baseline.

## Shared open decisions

The source documents do not yet determine:

- the PEP 517 build backend and dependency-lock strategy;
- whether the CLI uses Typer or standard-library `argparse`;
- CLI defaults not explicitly stated in the PRD;
- the exact local-source fingerprint algorithm;
- whether reusable workspace/cache data ultimately lives under each output
  directory or in a global cache;
- the exact supported `multisubs` JSON schema beyond fields confirmed by
  contract tests.

Each affected package identifies when the decision must be made. Implementers
must not silently turn an unresolved option into a permanent product contract.

## Source documents

- [Product requirements](../prd.md)
- [Architecture](../architecture.md)
- [Engineering conventions](../conventions.md)
- [Repository instructions](../../AGENTS.md)
