# Task 016.002: Collect and Publish Final Artifacts Safely

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 016.001 Define manifest and per-clip metadata contracts |
| PR | — |

## Objective

Build final artifacts from actual stage results and publish JSON only when its
referenced media/state is valid.

## Context and inputs

The manifest is the final run record, while stage caches remain independent
intermediate artifacts. Publication must not turn a temporary or failed clip
into an apparently completed one.

## Expected changes

- Aggregate normalized source, config, versions, transcription, generation,
  scoring, selection, rendering, warnings, and timings from pipeline results.
- Write per-clip JSON beside validated final media using controlled temporary
  files and atomic publication.
- Publish the final manifest last, with explicit run outcome and references only
  to successfully published or explicitly failed clips.
- Refuse silent overwrite/collision and validate all paths stay inside the run
  output layout.
- Keep stage caches independent from final artifact publication and preserve
  `--keep-intermediates` behavior.
- Add failure-injection tests for JSON serialization, clip metadata, manifest
  publication, and existing destinations.

## Acceptance criteria

- A completed clip JSON never points at a missing, partial, or unvalidated final
  media file.
- A final manifest is published only after its referenced per-clip artifacts
  reach their declared states.
- Publication failure preserves existing completed files and leaves temporary
  data distinguishable inside the private work area.
- Stage timings/warnings are derived from actual execution and are never
  fabricated to fill schema fields.
- Paths and source references are useful but contain no credentials or
  uncontrolled absolute remote metadata.
- Final artifact serialization is deterministic apart from declared run/time
  identity fields.

## Tests and validation

```bash
pytest tests/unit -k "artifact and (manifest or clip or publish)"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Full transactional publication across multiple filesystem objects is not
  required; ordered atomic files plus explicit outcome state are sufficient.
- Do not conflate final manifest publication with cache validity guarantees
  deferred to M4.
- The public subtitle result exposes requested and resolved template names.
  Final clip metadata records those names without a template source field.
- A published manifest marks the workspace complete. Re-running into that same
  destination is refused; an interrupted run without a manifest can reuse its
  stage caches.
