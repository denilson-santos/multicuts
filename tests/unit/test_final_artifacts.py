"""Contracts for versioned final artifacts before their publication."""

import copy
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from multicuts.artifacts import WorkspacePaths
from multicuts.final_artifacts import (
    FINAL_ARTIFACT_SCHEMA_VERSION,
    ClipMetadata,
    ClipOutcome,
    ClipReference,
    ClipRenderSettings,
    RunManifest,
    RunOutcome,
    RunSettings,
    RunVersions,
    ScoringSummary,
    SourceReference,
    StageSummary,
    StageTiming,
    derive_clip_title_summary,
    read_clip_metadata_payload,
    read_manifest_payload,
)
from multicuts.models import (
    SCORE_DIMENSIONS,
    AcquiredSource,
    ChecklistOutcome,
    ChecklistResult,
    MediaInfo,
    ScoreDimension,
    ScorePenalty,
    ScoreResult,
)


def _score() -> ScoreResult:
    return ScoreResult(
        score=74.0,
        base_score=78.0,
        confidence=0.8,
        dimensions=tuple(ScoreDimension(name, 70.0) for name in SCORE_DIMENSIONS),
        penalties=(ScorePenalty("weak_ending", 4.0, "Ending is weak"),),
        reason="A complete independent thought",
        scoring_schema_version=1,
        scoring_algorithm_version="heuristic-v1",
        scorer="heuristic-fallback",
    )


def _clip() -> ClipMetadata:
    return ClipMetadata(
        schema_version=FINAL_ARTIFACT_SCHEMA_VERSION,
        id="candidate-1",
        rank=1,
        source_start=10.0,
        source_end=24.0,
        render_start=9.8,
        render_end=24.2,
        duration=14.4,
        title="This is the first sentence.",
        summary="This is the first sentence. This explains the point.",
        candidate_text="This is the first sentence. This explains the point.",
        score=_score(),
        checklist=(ChecklistResult("duration", ChecklistOutcome.PASS),),
        transcript="This is the first sentence. This explains the point.",
        render_config=ClipRenderSettings(
            aspect_ratio="9:16",
            width=1080,
            height=1920,
            subtitles_enabled=True,
            template_requested="default",
            template_resolved="default",
            multisubs_version="4.3.0",
        ),
        output_path="clips/001-candidate-1.mp4",
    )


def _manifest() -> RunManifest:
    return RunManifest(
        schema_version=FINAL_ARTIFACT_SCHEMA_VERSION,
        run_id="run-1",
        created_at="2026-09-24T12:00:00+00:00",
        outcome=RunOutcome.COMPLETED,
        source=SourceReference("local", "fingerprint", "local:fingerprint"),
        source_fingerprint="fingerprint",
        config=RunSettings(
            clips=1,
            min_score=60,
            language_requested=None,
            min_duration=15.0,
            max_duration=60.0,
            candidate_budget=50,
            overlap_threshold=0.6,
            text_similarity_threshold=0.9,
            aspect_ratio="9:16",
            vertical_width=1080,
            vertical_height=1920,
            refinement_pre_roll=0.15,
            refinement_post_roll=0.25,
            refinement_search_radius=0.5,
            refinement_pause_threshold=0.4,
            subtitles_enabled=True,
            subtitle_template="default",
            template_directory_sha256=None,
            scorer="hybrid",
            transcription_model="large-v3",
            semantic_provider="openai",
            semantic_model="gpt-6-luna",
            semantic_reasoning_effort="max",
            semantic_fallback="heuristic",
        ),
        versions=RunVersions("0.1.0", "4.3.0", "7.0"),
        transcription=StageSummary("completed", 1, "4.3.0"),
        candidate_generation=StageSummary("completed", 3, "candidate-v1"),
        scoring=ScoringSummary(
            status="completed",
            count=2,
            configured_mode="hybrid",
            heuristic_count=0,
            hybrid_count=1,
            fallback_count=1,
            provider="openai",
            model="gpt-6-luna",
            scorer_version="hybrid-v1",
        ),
        selection=StageSummary("completed", 1, "selection-v1"),
        clips=(
            ClipReference(
                id="candidate-1",
                rank=1,
                status=ClipOutcome.COMPLETED,
                metadata_path="clips/001-candidate-1.json",
                output_path="clips/001-candidate-1.mp4",
            ),
        ),
        timings=(StageTiming("transcription", 4.2),),
        warnings=("semantic_fallback:provider_unavailable",),
    )


def test_clip_metadata_round_trip_preserves_score_and_time_domains() -> None:
    clip = _clip()
    payload = json.loads(json.dumps(clip.to_payload()))
    restored = read_clip_metadata_payload(payload)

    assert restored == clip
    assert payload["source_start"] == 10.0
    assert payload["render_start"] == 9.8
    assert payload["score"]["scorer"] == "heuristic-fallback"
    assert payload["score"]["provider"] is None
    assert payload["confidence"] == 0.8
    assert "template_source" not in payload["render_config"]

    stale_source = copy.deepcopy(payload)
    stale_source["render_config"]["template_source"] = "builtin"
    with pytest.raises(ValueError, match="incompatible fields"):
        read_clip_metadata_payload(stale_source)

    stale = copy.deepcopy(payload)
    stale["schema_version"] = 0
    with pytest.raises(ValueError, match="schema version"):
        read_clip_metadata_payload(stale)

    inconsistent = copy.deepcopy(payload)
    inconsistent["confidence"] = 0.1
    with pytest.raises(ValueError, match="conflicts"):
        read_clip_metadata_payload(inconsistent)


def test_manifest_round_trip_and_strict_schema() -> None:
    manifest = _manifest()
    payload = json.loads(json.dumps(manifest.to_payload()))
    assert read_manifest_payload(payload) == manifest

    future = copy.deepcopy(payload)
    future["schema_version"] = 2
    with pytest.raises(ValueError, match="schema version"):
        read_manifest_payload(future)

    extra = copy.deepcopy(payload)
    extra["secret_token"] = "must not be retained"
    with pytest.raises(ValueError, match="incompatible fields"):
        read_manifest_payload(extra)


def test_source_reference_excludes_raw_url_and_local_path() -> None:
    local = AcquiredSource(Path("/private/video.mp4"), "safe-fingerprint")
    assert SourceReference.from_source(local).reference == "local:safe-fingerprint"

    youtube = AcquiredSource(
        Path("/private/download.mp4"),
        "safe-fingerprint",
        source_kind="youtube",
        provider_id="abcdefghijk",
        title="Example",
        original_url="https://youtu.be/abcdefghijk?token=secret",
    )
    assert SourceReference.from_source(youtube).reference == (
        "https://www.youtube.com/watch?v=abcdefghijk"
    )


def test_title_summary_use_only_candidate_text() -> None:
    assert derive_clip_title_summary("  A useful opening.   More context here.  ") == (
        "A useful opening.",
        "A useful opening. More context here.",
    )


def test_artifact_invariants_reject_false_success_and_unsafe_paths() -> None:
    with pytest.raises(ValueError, match="zero-selection"):
        replace(_manifest(), outcome=RunOutcome.ZERO_SELECTION)

    with pytest.raises(ValueError, match="relative workspace path"):
        ClipReference(
            "candidate-1",
            1,
            ClipOutcome.COMPLETED,
            "../metadata.json",
            "clips/video.mp4",
        )


def test_run_settings_snapshot_excludes_source_and_output_paths() -> None:
    from multicuts.config import RunConfig

    config = RunConfig(
        source="https://youtu.be/abcdefghijk?token=secret",
        output_dir=Path("/private/output"),
        clips=2,
        min_score=65,
        aspect_ratio="original",
        subtitle_template="default",
        scorer="heuristic",
        model="large-v3",
    )
    snapshot = RunSettings.from_config(config)
    encoded = json.dumps(asdict(snapshot))
    assert "secret" not in encoded
    assert "/private/output" not in encoded
    assert snapshot.semantic_model is None
    assert snapshot.subtitle_template == "default"


def test_scoring_summary_rejects_false_semantic_provenance() -> None:
    with pytest.raises(ValueError, match="cannot claim a semantic scorer"):
        ScoringSummary(
            status="completed",
            count=1,
            configured_mode="hybrid",
            heuristic_count=0,
            hybrid_count=0,
            fallback_count=1,
            provider="openai",
            model="gpt-6-luna",
            scorer_version="hybrid-v1",
        )


def test_clip_text_keeps_scored_and_rendered_domains_separate() -> None:
    clip = replace(_clip(), transcript="A wider refined transcript.")
    assert read_clip_metadata_payload(clip.to_payload()) == clip
    assert clip.title == "This is the first sentence."

    silent = replace(
        clip,
        transcript="",
        render_config=ClipRenderSettings(
            aspect_ratio="original",
            width=1280,
            height=720,
            subtitles_enabled=False,
            template_requested=None,
            template_resolved=None,
            multisubs_version=None,
        ),
    )
    assert read_clip_metadata_payload(silent.to_payload()) == silent


def _inspect_media(_path: Path) -> MediaInfo:
    return MediaInfo(14.4, 1080, 1920, 1080, 1920, 0, 1)


def _workspace(tmp_path: Path) -> tuple[WorkspacePaths, Path]:
    from multicuts.artifacts import prepare_workspace

    source = AcquiredSource(Path("source.mp4"), "fingerprint")
    paths = prepare_workspace(tmp_path, source, cache_key="sha256-v1:cache")
    video = paths.root / _clip().output_path
    video.write_bytes(b"validated media")
    return paths, video


def test_publish_clip_metadata_requires_media_and_never_replaces_existing(
    tmp_path: Path,
) -> None:
    from multicuts.artifacts import publish_clip_metadata
    from multicuts.errors import ArtifactError

    paths, video = _workspace(tmp_path)
    video.unlink()
    with pytest.raises(ArtifactError, match="missing or incomplete"):
        publish_clip_metadata(paths, _clip(), inspect=_inspect_media)
    video.write_bytes(b"validated media")

    metadata = publish_clip_metadata(paths, _clip(), inspect=_inspect_media)
    original = metadata.read_bytes()
    assert read_clip_metadata_payload(json.loads(original)) == _clip()
    assert list(paths.work.iterdir()) == []
    with pytest.raises(ArtifactError, match="already exists"):
        publish_clip_metadata(paths, _clip(), inspect=_inspect_media)
    assert metadata.read_bytes() == original


@pytest.mark.parametrize("failure", ["serialization", "publication"])
def test_clip_metadata_failure_preserves_media_and_cleans_private_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from multicuts.artifacts import publish_clip_metadata
    from multicuts.errors import ArtifactError

    paths, video = _workspace(tmp_path)
    if failure == "serialization":

        def fail_dump(*_args: object, **_kwargs: object) -> None:
            raise TypeError("injected serialization failure")

        monkeypatch.setattr("multicuts.artifacts.json.dump", fail_dump)
    else:

        def fail_link(_source: Path, _target: Path) -> None:
            raise OSError("injected publication failure")

        monkeypatch.setattr("multicuts.artifacts.os.link", fail_link)

    with pytest.raises(ArtifactError, match="Could not publish"):
        publish_clip_metadata(paths, _clip(), inspect=_inspect_media)
    assert video.read_bytes() == b"validated media"
    assert not video.with_suffix(".json").exists()
    assert list(paths.work.iterdir()) == []


def test_clip_publication_rejects_unvalidated_media(
    tmp_path: Path,
) -> None:
    from multicuts.artifacts import publish_clip_metadata
    from multicuts.errors import ArtifactError

    paths, video = _workspace(tmp_path)

    def wrong_geometry(_path: Path) -> MediaInfo:
        return MediaInfo(14.4, 1920, 1080, 1920, 1080, 0, 1)

    with pytest.raises(ArtifactError, match="does not match metadata"):
        publish_clip_metadata(paths, _clip(), inspect=wrong_geometry)
    assert not video.with_suffix(".json").exists()


def test_manifest_publishes_last_and_rejects_missing_or_mismatched_clip(
    tmp_path: Path,
) -> None:
    from multicuts.artifacts import publish_clip_metadata, publish_run_manifest
    from multicuts.errors import ArtifactError

    paths, video = _workspace(tmp_path)
    with pytest.raises(ArtifactError, match="missing or incomplete"):
        publish_run_manifest(paths, _manifest())
    assert not paths.manifest.exists()

    publish_clip_metadata(paths, _clip(), inspect=_inspect_media)
    wrong = replace(
        _manifest(),
        clips=(replace(_manifest().clips[0], id="another-candidate"),),
    )
    with pytest.raises(ArtifactError, match="does not match metadata"):
        publish_run_manifest(paths, wrong)
    assert not paths.manifest.exists()

    manifest = publish_run_manifest(paths, _manifest())
    original = manifest.read_bytes()
    assert read_manifest_payload(json.loads(original)) == _manifest()
    assert video.is_file()
    assert list(paths.work.iterdir()) == []
    with pytest.raises(ArtifactError, match="already exists"):
        publish_run_manifest(paths, _manifest())
    assert manifest.read_bytes() == original


@pytest.mark.parametrize("failure", ["serialization", "publication"])
def test_manifest_publication_failure_preserves_completed_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from multicuts.artifacts import publish_clip_metadata, publish_run_manifest
    from multicuts.errors import ArtifactError

    paths, video = _workspace(tmp_path)
    metadata = publish_clip_metadata(paths, _clip(), inspect=_inspect_media)
    original = metadata.read_bytes()

    if failure == "serialization":

        def fail_dump(*_args: object, **_kwargs: object) -> None:
            raise TypeError("injected manifest serialization failure")

        monkeypatch.setattr("multicuts.artifacts.json.dump", fail_dump)
    else:

        def fail_link(_source: Path, _target: Path) -> None:
            raise OSError("injected manifest publication failure")

        monkeypatch.setattr("multicuts.artifacts.os.link", fail_link)
    with pytest.raises(ArtifactError, match="Could not publish"):
        publish_run_manifest(paths, _manifest())
    assert not paths.manifest.exists()
    assert metadata.read_bytes() == original
    assert video.is_file()
    assert list(paths.work.iterdir()) == []


def test_clip_publication_rejects_symlinked_output_directory(tmp_path: Path) -> None:
    from multicuts.artifacts import publish_clip_metadata
    from multicuts.errors import ArtifactError

    paths, video = _workspace(tmp_path)
    video.unlink()
    paths.raw_clips.rmdir()
    clips_dir = paths.root / "clips"
    clips_dir.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_video = outside / video.name
    outside_video.write_bytes(b"private media")
    try:
        clips_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not permit directory symlinks")

    with pytest.raises(ArtifactError, match="escapes"):
        publish_clip_metadata(paths, _clip(), inspect=_inspect_media)
    assert outside_video.read_bytes() == b"private media"
    assert not outside_video.with_suffix(".json").exists()
