# Task 011.003: Integrate and Verify YouTube Acquisition

| Field | Value |
| --- | --- |
| Status | in-review |
| Priority | P2 |
| Depends on | 011.002 Implement the yt-dlp adapter; Package 006 Transcript cache |
| PR | [#34](https://github.com/denilson-santos/multicuts/pull/34) |

## Objective

Route supported URLs through the new adapter, then reuse the existing media
probe, transcript cache, and downstream pipeline without provider leakage.

## Context and inputs

After acquisition, local and YouTube sources must share the same normalized
pipeline. Remote-source logging must retain useful stage context while omitting
credentials and full user identifiers where unnecessary.

## Expected changes

- Create an explicit acquisition workspace before source routing.
- Integrate local/YouTube dispatch into `run_pipeline` while preserving test
  substitution through one narrow boundary.
- Feed the returned local media path through existing ffprobe and transcription
  cache behavior unchanged.
- Add hermetic pipeline tests for supported URL routing, acquisition failures,
  source metadata, and transcript cache reuse.
- Add an opt-in integration test that verifies only the adapter contract against
  a controlled public fixture/source when the environment permits it.
- Document dependency installation/runtime expectations in the existing README
  if user-facing setup changes.

## Acceptance criteria

- A supported URL reaches probe/transcription through the same `AcquiredSource`
  contract as a local path.
- Local-source tests and behavior remain unchanged apart from the explicit
  workspace argument.
- A repeated compatible URL source can reuse the transcript cache by stable
  fingerprint without a second ASR call.
- Default tests perform no network or real download.
- Integration tests are marked and skip with a clear reason when prerequisites
  are absent.
- Logs/errors contain no cookies, authorization headers, or raw extractor data.

## Tests and validation

```bash
pytest tests/unit -k "youtube or source"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

When explicitly configured with network access and a controlled source:

```bash
pytest -m integration -k youtube
```

## Risks and exclusions

- Live site tests are inherently unstable and must not gate the hermetic default
  suite.
- Retention/cleanup of completed downloads remains a documented later decision;
  this task must keep paths isolated so a future policy can act safely.
