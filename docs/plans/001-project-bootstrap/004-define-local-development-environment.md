# Task 001.004: Define the Local Development Environment

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P0 |
| Depends on | 001.002 Configure quality tooling |

## Objective

Standardize the local Python development environment on the standard-library
`venv` module and document the exact activation and installation workflow for a
supported interpreter.

## Context and inputs

The repository supports Python `>=3.10,<3.14`, uses a small dependency tree, and
has no selected environment manager. The project should provide one predictable
workflow without adding Conda, Poetry, `uv`, a Dev Container, or another tool as
an implicit requirement.

## Implementation decisions

- Use Python 3.10 in the setup examples while allowing any explicitly verified
  Python 3.10–3.13 interpreter.
- Keep all setup commands in the contributor-facing root `README.md`; no custom
  activation or bootstrap script is required.
- Ignore the root `.venv/`, Python bytecode, test/lint caches, package metadata,
  and build outputs produced by the documented workflow.

## Expected changes

- Define `.venv/` at the repository root as the local environment location.
- Document creation with a selected supported interpreter, for example:

  ```bash
  python3.10 -m venv .venv
  ```

- Document POSIX activation:

  ```bash
  source .venv/bin/activate
  ```

- Document PowerShell activation:

  ```powershell
  .venv\Scripts\Activate.ps1
  ```

- Document installation of the editable project and its `dev` extra:

  ```bash
  python -m pip install --editable ".[dev]"
  ```

- Add `.venv/` and relevant generated environment files to `.gitignore`.
- State that CI creates its own isolated environment and does not depend on a
  developer's local `.venv`.
- Explain how to verify the active interpreter and run the repository quality
  commands after activation.

## Suggested sequence

1. Ensure task 001.002 exposes the `dev` installation target.
2. Select the supported interpreter used in the examples and explain how to
   substitute another supported 3.10–3.13 interpreter.
3. Add the ignore rules before creating any local environment.
4. Add the setup/activation instructions to the existing contributor-facing
   documentation without duplicating the entire engineering conventions file.
5. Execute the documented workflow in a clean temporary clone or workspace.

## Acceptance criteria

- A contributor with a supported Python interpreter can create `.venv` using
  only the documented commands.
- The editable project and all development tools install through the declared
  `dev` target.
- The active interpreter can be checked and is within `>=3.10,<3.14`.
- The documented Ruff, Pyright, pytest, and build commands run from the
  activated environment.
- `.venv/` is ignored and no environment contents are included in a Git diff.
- CI instructions remain independent from local activation scripts.

## Tests and validation

Run from a clean checkout with a supported interpreter:

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable ".[dev]"
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
python -m build
```

On PowerShell, use the documented activation command and equivalent Python
invocations. Verify that `git status` does not show `.venv/`.

## Risks and exclusions

- The exact interpreter executable name varies by operating system; examples
  must not imply that `python3.10` is universally installed.
- Do not commit an environment, activation script, lockfile, or machine-specific
  configuration.
- Do not add automatic shell activation, Conda files, Poetry metadata, `uv`
  metadata, or container configuration.
- Dependency installation still requires the package index/network; the
  hermetic test suite requirement applies after installation.
