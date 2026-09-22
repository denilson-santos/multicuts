# Task 011.001: Define Source Routing and Metadata Contracts

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P2 |
| Depends on | Packages 003 CLI and pipeline foundation, 004 Local source and media |
| PR | — |

## Objective

Define a narrow source-provider call contract, deterministic local/YouTube
routing, and normalized optional metadata without changing valid local input
semantics.

## Context and inputs

FR-ACQ-003 proposes `acquire(source, workspace) -> AcquiredSource`. The existing
pipeline's callable receives only `source`, so remote acquisition needs an
explicit controlled destination while domain code remains provider-independent.

## Expected changes

- Evolve the acquisition boundary to receive an explicit `Path` workspace.
- Define safe project-owned source metadata for source kind, provider ID, title,
  and original URL when available.
- Recognize supported YouTube URL forms without making network requests.
- Route filesystem-like inputs to local acquisition and recognized URLs to the
  future adapter.
- Reject unsupported URL schemes/hosts with an actionable `AcquisitionError`.
- Preserve local fingerprinting and no-modification guarantees.

## Acceptance criteria

- Source routing is deterministic and performs no network access by itself.
- Local paths, including relative/pathlike strings, retain existing behavior.
- Remote-only metadata is optional and local sources do not fabricate IDs/titles.
- Workspace paths are explicit, caller-controlled `Path` values.
- Domain models contain no yt-dlp object or broad extractor dictionary.

## Tests and validation

```bash
pytest tests/unit -k "source and (routing or metadata)"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Avoid overly broad URL matching that routes arbitrary sites into the YouTube
  adapter.
- A generic provider registry is unnecessary for the two documented input kinds.
