# Task 014.001: Define Rendering Contracts and the FFmpeg Boundary

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | Packages 004 Local source and media; 013 Boundary refinement |
| PR | — |

## Objective

Define validated render inputs/outputs and isolate FFmpeg command construction
and execution behind a narrow, testable boundary.

## Context and inputs

Rendering consumes a normalized local media path, probed presentation geometry,
and a refined interval. Domain code must not know command-line details or raw
subprocess output.

## Expected changes

- Define `RenderConfig`, raw-clip request/result, aspect-ratio mode, target
  geometry, and renderer provenance values.
- Validate supported `original`/`9:16` modes, positive dimensions, interval
  bounds, and destination/work paths.
- Define deterministic output naming that cannot traverse outside controlled
  workspace/clip directories.
- Implement pure argument-list command construction plus a narrow FFmpeg runner
  that translates failures to `RenderingError`.
- Capture/truncate diagnostics safely and preserve the external exception cause.
- Add unit tests for contracts, commands, stream mapping, and invalid inputs.

## Acceptance criteria

- Domain render values contain no subprocess objects or FFmpeg-specific payload
  dictionaries.
- Command construction always returns an argument list and never uses a shell.
- Inputs distinguish private temporary output from intended published output.
- Aspect-ratio and target-geometry validation fails before FFmpeg execution.
- Diagnostics are bounded and do not expose unrelated environment secrets.
- No command is executed in pure command-construction tests.

## Tests and validation

```bash
pytest tests/unit -k "render or ffmpeg"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not add a generic subprocess framework; the boundary should solve the
  concrete media commands used by the project.
- Subtitle filters and provider options do not belong in the raw cutter.
