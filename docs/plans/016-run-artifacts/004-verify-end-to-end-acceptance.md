# Task 016.004: Verify Local and YouTube End-to-End Acceptance

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 016.003 Complete pipeline and CLI outcome semantics; Package 011 YouTube acquisition |
| PR | [#45](https://github.com/denilson-santos/multicuts/pull/45) |

## Objective

Verify the documented M3/MVP acceptance behavior across local and supported
YouTube acquisition while keeping the default suite hermetic.

## Context and inputs

Most orchestration behavior can be tested with fake external boundaries. A
small marked suite should inspect real FFmpeg/ffprobe and the supported
`multisubs` contract; live YouTube/provider checks remain opt-in and unstable.

## Expected changes

- Add a hermetic end-to-end local pipeline test using a small controlled media
  boundary and real domain stages where practical.
- Assert manifest/per-clip schema, score/checklist provenance, duration,
  overlap, output paths, and single transcription call.
- Cover original and `9:16` geometry and subtitle-enabled/disabled branches at
  the narrowest appropriate integration level.
- Verify repeat runs reuse compatible transcription/stage artifacts and that
  template-only changes do not rerun ASR or scoring.
- Add marked opt-in local-tool and YouTube acquisition-to-output checks with
  clear prerequisite skips.
- Update existing README examples/output descriptions only where actual final
  CLI behavior differs from currently documented expectations.

## Acceptance criteria

- Hermetic tests cover AC-001 and AC-003–010, AC-012–014 without network, GPU,
  model downloads, or remote scorer credentials.
- Contract/marked integration tests cover AC-011 and real media tolerances when
  dependencies are present.
- The YouTube test proves downstream parity through normalized acquisition;
  live site access is opt-in and never gates the default suite.
- Multi-clip output performs one source transcription and derives each subtitle
  timeline from the cached source transcript.
- Failed render injection leaves no partial completed file or misleading final
  manifest state.
- User-facing CLI documentation matches the implemented output paths and
  completion summary.

## Tests and validation

```bash
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

When external dependencies and controlled fixtures are explicitly available:

```bash
pytest -m integration -k "render or subtitle or youtube"
```

## Integration evidence

PR #45 is merged into `main` at `e0834f7`. Its Python 3.10 quality and Python
3.13 compatibility checks passed. Before delivery, validation passed with
407 hermetic tests and 9 media integration tests, plus Ruff and Pyright.
The two live YouTube checks and real transcription check were skipped because
no opt-in source fixtures were configured; they remain optional acceptance
checks rather than default-suite gates.

## Risks and exclusions

- Live YouTube and remote semantic-provider checks are not reliable release
  gates; contract tests and hermetic fakes remain the default evidence.
- Packaging/release reproducibility and exhaustive cache/interruption cases
  belong to the following M4 planning batch.
