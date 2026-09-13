# Task 007.001: Define Candidate Contracts and Identity

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | Package 006 Transcript cache |
| PR | — |

## Objective

Add the smallest provider-independent models needed to represent semantic units
and candidate windows, including a stable identity contract.

## Context and inputs

The conceptual data model requires a candidate ID, interval, transcript span,
features, checklist, score, and status. This task introduces only the fields
needed through candidate generation; later packages add their own typed
evaluation values instead of pre-populating speculative structures.

## Expected changes

- Define immutable semantic-unit and candidate values with finite ordered
  seconds and nonempty text.
- Represent the transcript span or source-unit relationship without copying a
  raw provider payload.
- Define a candidate-generator version constant.
- Build stable IDs from canonical source fingerprint, start, end, and generator
  version values.
- Specify timestamp canonicalization precisely enough to avoid platform-specific
  IDs for equivalent inputs.
- Add model invariant and identity tests.

## Acceptance criteria

- Invalid, empty, non-finite, negative, or reversed intervals are rejected.
- Equivalent canonical identity inputs produce the same candidate ID.
- Changing source fingerprint, interval, or generator version changes the ID.
- Identity does not depend on filesystem paths, source titles, object hashes, or
  provider dictionaries.
- Models remain serializable with project-owned primitive values.

## Tests and validation

```bash
pytest tests/unit -k "candidate and (model or identity)"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Features, checklist outcomes, score results, and selection rank belong to
  packages 008–010.
- Timestamp canonicalization must not collapse meaningfully different source
  intervals; the chosen precision is an explicit implementation decision.
