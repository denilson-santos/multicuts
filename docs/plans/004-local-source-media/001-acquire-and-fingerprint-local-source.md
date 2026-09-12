# Task 004.001: Acquire and Fingerprint a Local Source

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | Package 002 Domain foundation |

## Objective

Validate a local source without modifying it and return a normalized
`AcquiredSource` with a stable fingerprint suitable for stage cache keys.

## Context and inputs

FR-ACQ-001 requires existing regular files and preservation of the original.
FR-ACQ-005 requires a deterministic identity that changes when the effective
input changes but leaves the exact algorithm open.

## Expected changes

- Accept the user source through a narrow local acquisition function.
- Resolve/normalize paths carefully while preserving a safe source reference.
- Reject missing paths, directories, and unreadable inputs with
  `AcquisitionError`.
- Select, document, and version a fingerprint strategy appropriate for local
  files.
- Return only normalized project-owned metadata; do not copy or alter the media.
- Avoid placing unsafe absolute paths or secrets in user-facing artifacts.

## Suggested sequence

1. Choose the fingerprint algorithm and define its version identifier.
2. Validate path type and readability before hashing.
3. Calculate the fingerprint without loading the entire file into memory.
4. Construct `AcquiredSource` with safe local metadata.
5. Test stable identity, changed content, invalid paths, and unchanged source
   bytes/metadata where practical.

## Acceptance criteria

- The same file contents produce the same fingerprint under the same algorithm
  version.
- Changed effective input changes the identity.
- Directories and missing/unreadable files fail before media probing.
- Acquisition never edits, moves, or deletes the original file.
- Domain consumers receive `AcquiredSource`, not filesystem stat objects.

## Tests and validation

```bash
pytest tests/unit -k "local_source or fingerprint"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- The selected local fingerprint is `sha256-v1:<hex digest>` over complete file
  contents, read in 1 MiB blocks. Equal bytes produce equal identities regardless
  of path; changing this algorithm requires a new version prefix.
- The source model carries the resolved local path and fingerprint. Do not copy
  the absolute path into user-facing artifacts or logs; artifact-safe display
  metadata belongs at the publication boundary.
- Full content hashes can be expensive for long videos; chunked reading avoids
  excessive memory but does not remove I/O cost.
- Metadata-only fingerprints risk stale cache hits and require explicit evidence
  before adoption.
- URL recognition and remote-source IDs belong to a later YouTube package.
