# Task 007.002: Build Semantic Units

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 007.001 Define candidate contracts and identity |
| PR | — |

## Objective

Derive deterministic timed semantic units from the normalized transcript using
only available structural and timing evidence.

## Context and inputs

FR-CAN-001 names sentences, punctuation, pauses, word timestamps,
language-aware boundaries, and topic changes when available. The normalized
transcript currently exposes segments and words but does not guarantee every
word is timed.

## Expected changes

- Prefer provider-normalized segment boundaries when they are valid and useful.
- Use punctuation and measured pauses to join or split text at natural points.
- Keep language handling limited to reliable normalized signals and simple
  punctuation rules.
- Define behavior for missing word timings, untimed segments, overlapping
  provider intervals, and trailing text.
- Return semantic units in stable source order without gaps invented by the
  algorithm.
- Add compact multilingual and partial-timing fixtures.

## Acceptance criteria

- The same transcript and unit-generator version always produce the same units.
- Unit intervals are sourced from real transcript timestamps and stay within the
  transcript duration.
- Text order is preserved and usable timed content is not duplicated.
- Missing timing produces an explicit skip/failure policy; it never triggers
  timestamp interpolation presented as ASR data.
- Pause and punctuation thresholds are named, tested, and tied to generator
  versioning.

## Tests and validation

```bash
pytest tests/unit -k "semantic_unit"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Language-specific NLP libraries and semantic topic models are out of scope.
- The first heuristic will be imperfect on transcripts with sparse punctuation;
  fixtures should establish behavior without claiming linguistic completeness.

## Implementation decision

Version `1` closes units on terminal punctuation or a measured pause of at least
`0.75` seconds. It prefers timed normalized segments and falls back to timed
words when those segments cannot produce any duration-valid candidate. It merges
overlaps and excludes untimed content.
