# Task 003.001: Build the CLI Command Surface

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | Package 002 Domain foundation |

## Objective

Expose `multicuts generate SOURCE` with the complete minimum option surface and
convert parsed values into a validated `RunConfig`.

## Context and inputs

FR-CLI-001/002 define the command, source argument, and required options. The
source may eventually be a local path or URL, so parsing must preserve it for the
acquisition boundary rather than deciding the provider inside the CLI.

## Expected changes

- Select and record Typer or standard-library `argparse` before implementation.
- Declare the `multicuts` console entry point in package metadata.
- Add `generate SOURCE` and all options listed by FR-CLI-002.
- Map omitted/`auto` language and path-valued options consistently.
- Construct `RunConfig` through its validation boundary.
- Provide concise help that describes the viral-potential score as a ranking
  heuristic, not a probability.

## Suggested sequence

1. Resolve the CLI-library and unspecified-default decisions.
2. Declare the entry point and command hierarchy.
3. Add options without business or provider logic in callbacks.
4. Convert parsed values to `RunConfig` once.
5. Test help, a representative valid invocation, and invalid inputs.

## Acceptance criteria

- Installed users can run `multicuts generate SOURCE`.
- Help exposes every option required by FR-CLI-002.
- Parsed values are not retained as a broad dictionary beyond the parser.
- Configuration errors are passed to the error-mapping boundary.
- Parsing does not access the network, filesystem media, FFmpeg, or models.

## Implementation decisions

- Use the Python standard-library `argparse` module to avoid adding a runtime
  dependency for the initial command surface.
- Default `--output-dir` to `multicuts-output`, `--clips` to `5`, `--min-score`
  to `0`, and `--aspect-ratio` to `original`, matching the documented CLI
  examples and avoiding an undocumented score filter.
- Use the documented `yellow-pop` built-in as the initial subtitle-template
  default and `heuristic` as the initial scorer name. The PRD lists
  `yellow-pop` among the supported `multisubs` presentations.
- Keep `default` as the model parser sentinel because the repository does not
  document a provider model default. The transcription adapter must resolve
  this before invoking `multisubs`, or the CLI default must become required
  when that contract is implemented.
- Keep the pipeline callback injectable so tests can verify the CLI boundary
  without external tools. Invoking the installed command before the pipeline
  task is complete raises an explicit runtime error instead of reporting a
  successful no-op.

## Tests and validation

```bash
pytest tests/unit -k cli
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not add aliases, profiles, interactive prompts, or platform-specific
  options absent from the PRD.
- Do not make a local-path existence check during generic source parsing; local
  acquisition owns that decision.
- Do not add Rich solely to format initial help/progress output.
