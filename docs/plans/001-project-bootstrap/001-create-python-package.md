# Task 001.001: Create the Python Package

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P0 |
| Depends on | None |

## Objective

Create a standards-based, importable `src`-layout package that declares the
supported Python range and provides the base for all later modules.

## Context and inputs

Use the runtime/development baseline in `docs/architecture.md` and the Python
compatibility rules in `docs/conventions.md`. Before editing, select and record a
minimal maintained PEP 517 backend; the source documents do not prescribe one.

## Expected changes

- Add `pyproject.toml` with build-system and project metadata.
- Declare `requires-python = ">=3.10,<3.14"`.
- Add `src/multicuts/__init__.py` with only package-level metadata that has a
  current consumer.
- Add the minimum test structure and an import/package metadata test.
- Keep runtime dependencies empty until a package requiring them is implemented;
  do not install FFmpeg as a Python dependency.

## Suggested sequence

1. Record the selected build backend and why it satisfies Python 3.10–3.13.
2. Create the `pyproject.toml` build and project sections.
3. Create the package root without speculative modules.
4. Add a bootstrap test that imports `multicuts` from an installed/editable
   environment.
5. Build both source and wheel distributions and inspect their contents.

## Acceptance criteria

- The project installs into a clean supported environment.
- `python -c "import multicuts"` succeeds after installation.
- Wheel and source distributions contain the package and required project files.
- Metadata does not claim an undefined final license or unsupported Python.
- No CLI, domain logic, provider adapter, or unused abstraction is added.

## Tests and validation

```bash
pytest -m "not integration"
python -m build
```

Inspect the built archives to ensure `src/` layout configuration is correct.

## Risks and exclusions

- The package version strategy is open; choose a minimal development value
  without implying a public release.
- Do not create every directory shown in the architectural target tree.
- Do not add a dependency lockfile until its ownership and update process are
  decided.
