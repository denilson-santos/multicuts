# Task 011.002: Implement the yt-dlp Adapter

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P2 |
| Depends on | 011.001 Define source routing and metadata contracts |
| PR | — |

## Objective

Download one supported YouTube source with the yt-dlp Python API into a
controlled workspace and return normalized source data.

## Context and inputs

The adapter owns all yt-dlp configuration and unstable payload parsing. The
pipeline needs one usable local media path and safe metadata before existing
ffprobe/transcription stages run.

## Expected changes

- Add the runtime dependency only after verifying supported Python 3.10–3.13
  bounds.
- Configure the yt-dlp Python API for one source and an explicit destination
  template rooted inside the supplied workspace.
- Select a suitable downloadable video/audio format without requiring later
  stages to understand yt-dlp.
- Normalize final path, source ID, title, canonical/original URL, and a stable
  effective-source fingerprint.
- Validate that reported/downloaded paths remain under the workspace and exist.
- Translate expected downloader/extractor/schema failures to safe
  `AcquisitionError`s with exception chaining.
- Unit test through a fake yt-dlp boundary and checked-in payload fixtures.

## Acceptance criteria

- No subprocess shell command is used for yt-dlp.
- The adapter cannot publish or return a file outside the supplied workspace.
- Exactly one source is acquired; playlists/batches are rejected or disabled.
- Raw yt-dlp payloads and credentials never leave the adapter or appear in logs.
- Fingerprint inputs are deterministic, documented, and change with the
  effective media identity rather than title alone.
- Missing output and malformed metadata cannot appear successful.

## Tests and validation

```bash
pytest tests/unit -k "youtube_adapter"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Format availability varies by source. Keep selection minimal and actionable;
  do not build a generalized format policy engine.
- Cookie/account support and restricted-content workarounds are explicitly out
  of scope.
