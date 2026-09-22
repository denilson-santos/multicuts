# Task 008.002: Compute Deterministic Features

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 008.001 Define feature and checklist contracts |
| PR | [#31](https://github.com/denilson-santos/multicuts/pull/31) |

## Objective

Compute the minimal deterministic evidence used by initial checklist rules and
heuristic scoring from a candidate and normalized transcript.

## Context and inputs

The architecture names duration, words per second, pause ratios, filler signals,
boundary quality, and transcript confidence as likely features. Only values
supported by actual timestamps/text may be treated as observed.

## Expected changes

- Compute candidate duration and timed speech density.
- Aggregate real word/segment pauses and confidence when the necessary data is
  present.
- Extract simple, versioned opening/ending, filler, and context-dependence text
  signals.
- Return missing evidence explicitly instead of substituting favorable values.
- Keep feature computation pure and deterministic.
- Add fixtures for partial timings, missing confidence, multilingual text,
  punctuation, and interval edges.

## Acceptance criteria

- Features depend only on candidate/transcript/config inputs and feature version.
- Ratios and aggregates use documented denominators and stay in validated ranges.
- Missing confidence or timing produces `None`/unknown evidence, not zero-quality
  or perfect-quality assumptions.
- Candidate boundaries select the intended transcript span with explicit
  floating-point edge tests.
- No FFmpeg, provider, network, or filesystem call occurs in feature computation.

## Tests and validation

```bash
pytest tests/unit -k "candidate_features"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Transcript gaps are only a proxy for silence and must be named accordingly.
- Filler/context word lists can be language-sensitive; the initial supported
  behavior and unknown-language fallback need explicit tests.
