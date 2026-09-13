# Package 003: CLI and Pipeline Foundation

| Field | Value |
| --- | --- |
| Milestone | M0 — Foundation |
| Status | completed |
| Priority | P1 |
| Depends on | 002 Domain foundation |
| Unlocks | End-to-end orchestration integration for later packages |
| PRs | [#13](https://github.com/denilson-santos/multicuts/pull/13), [#14](https://github.com/denilson-santos/multicuts/pull/14), [#19](https://github.com/denilson-santos/multicuts/pull/19) |

## Objective and expected outcome

Expose the documented `multicuts SOURCE` command, translate its inputs
into `RunConfig`, and establish a readable synchronous pipeline boundary with
consistent logging and exit codes. The command must not report success for
stages that have not yet been implemented.

## Context

Milestone 0 requires a CLI skeleton, logging, and errors. Keeping parsing,
semantic validation, orchestration, and exception mapping separate allows the
local acquisition and transcription packages to integrate without moving domain
logic into the console layer.

## Included scope

- command entry point and the option surface required by FR-CLI-001/002;
- translation of parsed values into `RunConfig`;
- one explicit synchronous orchestration entry point;
- stage-aware diagnostics through standard logging;
- mapping project errors to FR-CLI-003 exit codes;
- unit tests that substitute the pipeline boundary rather than external tools.

## Out of scope

- acquisition, probing, transcription, candidate, scoring, or rendering logic;
- rich progress UI or a dependency used only for presentation;
- provider configuration beyond documented generic `--scorer` and `--model`
  inputs;
- fake generated clips, placeholder artifacts, or a successful no-op run.

## Requirements and established decisions

- [PRD: CLI](../../prd.md#91-cli)
- [PRD: main flow](../../prd.md#8-main-flow)
- [PRD: observability](../../prd.md#14-observability)
- [Architecture: `cli.py`](../../architecture.md#clipy)
- [Architecture: `pipeline.py`](../../architecture.md#pipelinepy)
- [Conventions: logging and terminal output](../../conventions.md#17-logging-and-terminal-output)

## Likely components

- `src/multicuts/cli.py`
- `src/multicuts/pipeline.py`
- the console-script declaration in `pyproject.toml`
- `tests/unit/`

## Task index

| Task | Status | Depends on | PR | Outcome |
| --- | --- | --- | --- | --- |
| [001 Build CLI command surface](001-build-cli-command-surface.md) | completed | Package 002 | [#13](https://github.com/denilson-santos/multicuts/pull/13) | Documented command and options parse into `RunConfig` |
| [002 Add pipeline orchestration boundary](002-add-pipeline-orchestration-boundary.md) | completed | 001 | [#14](https://github.com/denilson-santos/multicuts/pull/14) | One readable synchronous application entry point |
| [003 Map errors and logging](003-map-errors-and-logging.md) | completed | 002 | [#19](https://github.com/denilson-santos/multicuts/pull/19) | Stable exit behavior and safe diagnostics |

## Completion criteria

- `multicuts SOURCE --help` exposes every minimum MVP option.
- CLI values are normalized once into `RunConfig` and are not passed around as
  an untyped dictionary.
- Pipeline orchestration contains no provider details or product algorithms.
- Known project errors map to exits 2–6 and unexpected failures map to exit 1.
- CLI tests are hermetic and assert observable output/exit behavior.

## Risks, assumptions, and open questions

- The PRD permits Typer or `argparse`; task 001 selected `argparse` without an
  additional CLI dependency.
- Defaults for `--clips`, `--min-score`, scorer/model, output directory, and
  subtitle template were recorded in task 001 and may need review when the
  end-to-end pipeline is available.
- Until downstream stages exist, tests should invoke the CLI with a substituted
  orchestration boundary. Production code must surface incomplete capability
  honestly rather than return a false success.
