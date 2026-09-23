# Task 014.003: Render Center-Cropped Vertical Clips

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 014.002 Render accurate original-geometry clips |
| PR | — |

## Objective

Add deterministic center crop and resize for valid configurable `9:16` output.

## Context and inputs

Decision D-008 requires center crop with no smart reframing. Crop calculations
must use presentation geometry and yield encoder-compatible dimensions without
changing the selected time interval.

## Expected changes

- Calculate the largest centered `9:16` crop within normalized source
  presentation geometry.
- Resize to the validated configured target resolution and define rounding for
  codec-compatible even dimensions.
- Compose crop/scale with rotation normalization in an explicit stable filter
  order.
- Preserve the original-mode audio and timing behavior.
- Add portrait, landscape, square, rotated, and odd-dimension command tests plus
  marked output-geometry integration tests.

## Acceptance criteria

- Output display geometry is `9:16` within explicit tolerance and matches the
  configured target dimensions.
- The crop is centered and remains within source presentation bounds for every
  supported geometry fixture.
- No face tracking, subject detection, or manual offset behavior is introduced.
- Vertical rendering does not alter the refined interval or trigger
  transcription/scoring work.
- Final probed geometry is recorded for package 015 subtitle layout.

## Tests and validation

```bash
pytest tests/unit -k "render and (vertical or geometry)"
pytest -m integration -k "render and vertical"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Crop/filter order around rotation is easy to get wrong; fixture assertions
  must use displayed output geometry, not only coded metadata.
- Manual crop offsets remain an open post-MVP question.
