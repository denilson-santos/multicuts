"""Output-local workspace and normalized transcript persistence tests."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.artifacts import (
    InvalidTranscriptArtifactError,
    prepare_workspace,
    read_transcript,
    transcription_cache_key,
    write_transcript,
)
from multicuts.errors import ArtifactError
from multicuts.models import AcquiredSource, Transcript, TranscriptSegment, Word


@pytest.fixture
def transcript() -> Transcript:
    return Transcript(
        language_requested=None,
        language_detected="pt",
        duration=2.123456789,
        text="Olá, 世界!",
        segments=(TranscriptSegment("Olá, 世界!", 0.0, 2.123456789),),
        words=(
            Word("Olá,", 0.125123456, 0.75, 0.987654321),
            Word("世界!", None, None),
        ),
        provider="multisubs",
        provider_version="4.1.0",
    )


@pytest.fixture
def cache_key() -> str:
    return transcription_cache_key(
        source_fingerprint="sha256-v1:abc",
        provider="multisubs",
        provider_version="4.1.0",
        model="default",
        language=None,
    )


def test_workspace_paths_are_controlled_and_isolated(
    tmp_path: Path, cache_key: str
) -> None:
    source = AcquiredSource(Path("/videos/bad?name.mp4"), "sha256-v1:abc")
    paths = prepare_workspace(tmp_path / "output", source, cache_key=cache_key)
    same = prepare_workspace(tmp_path / "output", source, cache_key=cache_key)
    different_source = prepare_workspace(
        tmp_path / "output",
        AcquiredSource(source.local_path, "sha256-v1:def"),
        cache_key=cache_key,
    )
    other_key = prepare_workspace(
        tmp_path / "output", source, cache_key=cache_key + "1"
    )

    assert paths == same
    assert paths.root.name.startswith("source-")
    assert "bad" not in paths.root.name
    assert paths.root != different_source.root
    assert paths.root != other_key.root
    renamed_source = prepare_workspace(
        tmp_path / "output",
        AcquiredSource(Path("/elsewhere/renamed.mp4"), source.fingerprint),
        cache_key=cache_key,
    )
    assert renamed_source == paths
    assert paths.source_metadata.parent.is_dir()
    assert paths.transcript.parent.is_dir()
    assert paths.work.is_dir()
    assert paths.transcript == paths.root / "transcript" / "transcript.json"
    assert paths.work == paths.root / ".work"


def test_workspace_rejects_existing_completed_output(
    tmp_path: Path, cache_key: str
) -> None:
    source = AcquiredSource(Path("source.mp4"), "sha256-v1:abc")
    paths = prepare_workspace(tmp_path, source, cache_key=cache_key)
    paths.manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(ArtifactError, match="Completed output already exists"):
        prepare_workspace(tmp_path, source, cache_key=cache_key)


def test_transcript_round_trip_preserves_unicode_timing_and_provenance(
    tmp_path: Path, cache_key: str, transcript: Transcript
) -> None:
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:abc"),
        cache_key=cache_key,
    )
    write_transcript(paths, transcript, cache_key=cache_key, replace=False)

    assert read_transcript(paths, cache_key=cache_key) == transcript
    contents = paths.transcript.read_text(encoding="utf-8")
    assert "Olá, 世界!" in contents
    assert "0.125123456" in contents
    assert contents.endswith("\n")
    assert list(paths.work.iterdir()) == []
    assert read_transcript(paths, cache_key=cache_key + "stale") is None


def test_transcript_refuses_unapproved_replacement(
    tmp_path: Path, cache_key: str, transcript: Transcript
) -> None:
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:abc"),
        cache_key=cache_key,
    )
    write_transcript(paths, transcript, cache_key=cache_key, replace=False)
    changed = replace(transcript, text="Novo texto")

    with pytest.raises(ArtifactError, match="refusing to overwrite"):
        write_transcript(paths, changed, cache_key=cache_key, replace=False)
    assert read_transcript(paths, cache_key=cache_key) == transcript

    write_transcript(paths, changed, cache_key=cache_key, replace=True)
    assert read_transcript(paths, cache_key=cache_key) == changed


def test_transcript_refuses_symlinked_cache_file(
    tmp_path: Path, cache_key: str, transcript: Transcript
) -> None:
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:abc"),
        cache_key=cache_key,
    )
    outside = tmp_path / "outside.json"
    outside.write_text("private", encoding="utf-8")
    try:
        paths.transcript.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not permit test symlinks")

    with pytest.raises(ArtifactError, match="regular file"):
        read_transcript(paths, cache_key=cache_key)
    with pytest.raises(ArtifactError, match="regular file"):
        write_transcript(paths, transcript, cache_key=cache_key, replace=True)
    assert outside.read_text(encoding="utf-8") == "private"


def test_failed_publication_leaves_no_completed_artifact(
    tmp_path: Path,
    cache_key: str,
    transcript: Transcript,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:abc"),
        cache_key=cache_key,
    )

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr("multicuts.artifacts.os.replace", fail_replace)
    with pytest.raises(ArtifactError, match="Could not publish"):
        write_transcript(paths, transcript, cache_key=cache_key, replace=False)

    assert not paths.transcript.exists()
    assert list(paths.work.iterdir()) == []


def test_failed_recomputation_preserves_previous_complete_artifact(
    tmp_path: Path,
    cache_key: str,
    transcript: Transcript,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:abc"),
        cache_key=cache_key,
    )
    write_transcript(paths, transcript, cache_key=cache_key, replace=False)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr("multicuts.artifacts.os.replace", fail_replace)
    with pytest.raises(ArtifactError, match="Could not publish"):
        write_transcript(
            paths,
            replace(transcript, text="Novo texto"),
            cache_key=cache_key,
            replace=True,
        )

    assert read_transcript(paths, cache_key=cache_key) == transcript
    assert list(paths.work.iterdir()) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version=99),
        lambda payload: payload["transcript"]["segments"].clear(),
        lambda payload: payload["transcript"]["words"][0].pop("end"),
        lambda payload: payload["transcript"]["words"][0].update(start=None),
        lambda payload: payload["transcript"].update(duration=True),
        lambda payload: payload["transcript"].update(provider_version=""),
    ],
)
def test_invalid_transcript_artifact_is_rejected(
    tmp_path: Path,
    cache_key: str,
    transcript: Transcript,
    mutation: object,
) -> None:
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:abc"),
        cache_key=cache_key,
    )
    write_transcript(paths, transcript, cache_key=cache_key, replace=False)
    payload = json.loads(paths.transcript.read_text(encoding="utf-8"))
    assert callable(mutation)
    mutation(payload)
    paths.transcript.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidTranscriptArtifactError):
        read_transcript(paths, cache_key=cache_key)


def test_nonfinite_json_is_rejected(
    tmp_path: Path, cache_key: str, transcript: Transcript
) -> None:
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:abc"),
        cache_key=cache_key,
    )
    write_transcript(paths, transcript, cache_key=cache_key, replace=False)
    contents = paths.transcript.read_text(encoding="utf-8").replace(
        "2.123456789", "NaN", 1
    )
    paths.transcript.write_text(contents, encoding="utf-8")

    with pytest.raises(InvalidTranscriptArtifactError, match="valid JSON"):
        read_transcript(paths, cache_key=cache_key)


def test_cache_key_changes_only_for_transcription_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def key(
        *,
        source_fingerprint: str = "sha256-v1:abc",
        provider: str = "multisubs",
        provider_version: str = "4.1.0",
        model: str = "default",
        language: str | None = None,
    ) -> str:
        return transcription_cache_key(
            source_fingerprint=source_fingerprint,
            provider=provider,
            provider_version=provider_version,
            model=model,
            language=language,
        )

    baseline = key()
    assert baseline == key()
    assert key(source_fingerprint="sha256-v1:def") != baseline
    assert key(provider="other") != baseline
    assert key(provider_version="4.2.0") != baseline
    assert key(model="small") != baseline
    assert key(language="pt") != baseline

    monkeypatch.setattr("multicuts.artifacts.TRANSCRIPTION_STAGE_VERSION", 2)
    assert key() != baseline
    monkeypatch.setattr("multicuts.artifacts.TRANSCRIPTION_STAGE_VERSION", 1)
    monkeypatch.setattr("multicuts.artifacts.TRANSCRIPT_SCHEMA_VERSION", 2)
    assert key() != baseline
    monkeypatch.setattr("multicuts.artifacts.TRANSCRIPT_SCHEMA_VERSION", 1)
    monkeypatch.setattr("multicuts.artifacts.TRANSCRIPTION_TASK", "translate")
    assert key() != baseline
