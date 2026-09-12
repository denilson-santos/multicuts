# Task 006.001: Create Workspace and Artifact Paths

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | Package 005 Multisubs transcription |
| PR | [#21](https://github.com/denilson-santos/multicuts/pull/21) |

## Objective

Define the filesystem contract needed to keep source metadata, normalized
transcripts, and incomplete work separate from completed artifacts.

## Context and inputs

The architecture assigns filesystem ownership to `artifacts.py` and shows a
source-specific output directory with a private `.work` area. PRD open question
10 leaves a future global cache undecided, so this task must keep paths
stage-specific and relocatable.

## Expected changes

- Add the narrow artifact-path behavior required by source metadata and
  `transcript/transcript.json`.
- Derive safe source/run directory names without trusting raw titles or paths.
- Keep incomplete provider and write artifacts under a private working area.
- Create directories deliberately with `pathlib.Path`.
- Detect completed-output collisions and never silently overwrite them.
- Avoid introducing a repository class or generalized artifact graph.

## Suggested sequence

1. Decide and record the initial workspace location while preserving an explicit
   output-root input.
2. Define deterministic paths for source metadata, transcript, and temporary
   files.
3. Sanitize externally supplied source labels used in directory names.
4. Add `tmp_path` tests for creation, isolation, and collisions.

## Acceptance criteria

- All paths are derived from an explicit output/workspace root.
- Incomplete files cannot be mistaken for completed transcript artifacts.
- Existing completed artifacts are detected before a write.
- Two distinct sources/runs do not collide under tested naming rules.
- No database, global singleton, or repository abstraction is added.

## Tests and validation

```bash
pytest tests/unit -k "artifact and path"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- The permanent choice between per-output and global cache remains open. Record
  the initial choice as an implementation decision, not an immutable product
  contract.
- Source titles and provider text are untrusted and must not escape the selected
  root.
- Complete run manifests and per-clip paths belong to later packages.

## Implementation decision

Use a caller-provided output root with one directory per source fingerprint and
transcription key. Directory names use only a digest, so untrusted source labels
cannot affect cache identity or escape the root. Reserve `source/metadata.json`,
`transcript/transcript.json`, and `.work/` without writing a full source or run
manifest in this package.
