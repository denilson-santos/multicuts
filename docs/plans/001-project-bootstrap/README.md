# Package 001: Project Bootstrap

| Field | Value |
| --- | --- |
| Milestone | M0 — Foundation |
| Status | in-progress |
| Priority | P0 |
| Depends on | None |
| Unlocks | 002 Domain foundation |

## Objective and expected outcome

Establish the smallest installable Python project that can run the documented
quality gates consistently in development and CI. Completion provides a
`src`-layout package, a test entry point, declared compatibility with Python
3.10–3.13, and repeatable lint, type, test, and build checks.

## Context

The repository has no package manifest or source tree. The architecture requires
standard packaging through `pyproject.toml`, and Milestone 0 explicitly includes
the package and CI. Establishing these contracts first prevents later packages
from inventing incompatible layouts or tool settings.

## Included scope

- `pyproject.toml` with project metadata, Python compatibility, build metadata,
  Ruff, Pyright, and pytest configuration;
- a documented local Python `venv` workflow using a root `.venv/` directory and
  an ignore rule that keeps the environment out of version control;
- `src/multicuts/__init__.py` and only the package metadata needed to import it;
- the initial `tests/` structure with at least one meaningful bootstrap test;
- CI checks for formatting, linting, types, hermetic tests, and package build;
- developer dependencies required by the documented quality gates.

## Out of scope

- CLI commands and entry points;
- domain models, configuration, and project exceptions;
- runtime adapters or heavy media dependencies;
- Conda, Poetry, a Dev Container, or another environment manager;
- lockfile/release automation unless its strategy is explicitly decided;
- empty modules or directories created only to mirror the complete architecture.

## Requirements and established decisions

- [Architecture: technology baseline](../../architecture.md#3-technology-baseline)
- [Architecture: package structure](../../architecture.md#5-package-structure)
- [Conventions: Python compatibility](../../conventions.md#3-python-compatibility)
- [Conventions: formatting and linting](../../conventions.md#4-formatting-and-linting)
- [Conventions: type checking](../../conventions.md#5-type-checking)
- [Conventions: tests](../../conventions.md#20-tests)
- PRD decisions D-001 and the Milestone 0 package/CI deliverables.

## Likely components

- `pyproject.toml`
- `src/multicuts/__init__.py`
- `tests/`
- `.github/workflows/`

## Task index

| Task | Status | Depends on | Outcome |
| --- | --- | --- | --- |
| [001 Create Python package](001-create-python-package.md) | completed | None | Importable `src`-layout package |
| [002 Configure quality tooling](002-configure-quality-tooling.md) | completed | 001 | Local Ruff, Pyright, pytest, and build configuration |
| [003 Add CI and build validation](003-add-ci-and-build-validation.md) | in-progress | 002 | Automated validation on supported changes |
| [004 Define local development environment](004-define-local-development-environment.md) | planned | 002 | Reproducible Python `venv` workflow |

## Completion criteria

- The package installs and imports on a supported Python version.
- Configuration advertises `>=3.10,<3.14` without using Python features newer
  than 3.10.
- `ruff format --check .`, `ruff check .`, `pyright`,
  `pytest -m "not integration"`, and `python -m build` succeed.
- CI runs the same relevant checks without network-dependent tests or model
  downloads.
- A new contributor can create `.venv`, install the declared development extras,
  and run the documented checks without an undocumented tool manager.
- `.venv/` and generated environment files cannot be staged accidentally.
- No speculative application modules or runtime behavior are added.

## Risks, assumptions, and open questions

- The build backend is not selected by existing documentation. Select a minimal,
  maintained PEP 517 backend before task 001 is implemented and record the
  decision in that change.
- Task 001 uses `setuptools.build_meta` with `setuptools>=68`. This maintained,
  standards-based backend supports the project's Python range without selecting
  a dependency manager or deciding the still-open lockfile strategy.
- The supported interpreter used to create `.venv` must be selected explicitly
  from Python 3.10–3.13; the environment must not silently use an unsupported
  system Python.
- The lockfile strategy is open. It does not block declaring dependency bounds.
- The initial package version and license metadata are not specified. Do not
  publish a release or invent a final license as part of this package.
- Required GitHub status checks should be enabled only after the workflow names
  are stable and have produced successful runs.
