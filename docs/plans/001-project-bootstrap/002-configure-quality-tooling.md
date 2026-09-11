# Task 001.002: Configure Quality Tooling

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P0 |
| Depends on | 001.001 Create the Python package |

## Objective

Configure the documented formatter, linter, type checker, and test runner so the
same commands can be used locally and in CI.

## Context and inputs

The conventions prescribe Ruff, Pyright, and pytest, including initial Ruff and
Pyright settings. The default test selection must exclude integration tests and
must not require network access, models, GPU, YouTube, FFmpeg, or credentials.

## Implementation decisions

- Expose build and quality tools through the `dev` optional dependency group,
  with major-version bounds but no lockfile.
- Exclude `docs/` from Ruff because its Markdown contains conceptual and partial
  Python snippets rather than executable project code. Source and tests remain
  fully covered by formatting and lint checks.
- Enable pytest strict configuration and marker validation so configuration
  mistakes fail early.

## Expected changes

- Add Ruff configuration with `target-version = "py310"`, line length 88, and
  lint selections `E`, `F`, `I`, `B`, and `UP`.
- Add Pyright configuration covering `src` and `tests`, Python 3.10, and basic
  type checking.
- Register the pytest `integration` marker and set deterministic test discovery.
- Declare development/build dependencies in the chosen project-supported form,
  with a stable `dev` installation target for the local `venv` workflow.
- Ensure shared/public interfaces and tests are included in type checking.

## Suggested sequence

1. Add the exact baseline tool settings from `docs/conventions.md`.
2. Register test markers before integration tests exist so later additions do
   not produce unknown-marker warnings.
3. Run each check independently and correct configuration errors.
4. Run the complete non-integration validation sequence.

## Acceptance criteria

- Ruff targets Python 3.10 and uses the documented lint families.
- Pyright analyzes `src` and `tests` in basic mode.
- `pytest -m "not integration"` selects only hermetic tests.
- Tool configuration is centralized in `pyproject.toml` unless a tool requires a
  separate file.
- No formatter/linter exceptions are added without a specific justification.

## Tests and validation

```bash
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
```

## Risks and exclusions

- Do not enable strict typing as a separate bootstrap refactor.
- Do not add coverage thresholds; coverage is a diagnostic under current
  conventions.
- Do not make the default pytest command depend on external binaries.
