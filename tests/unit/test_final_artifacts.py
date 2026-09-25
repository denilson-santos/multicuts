"""Contracts for versioned final artifacts before their publication."""

import copy
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

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
            template_source="builtin",
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
            template_source=None,
            multisubs_version=None,
        ),
    )
    assert read_clip_metadata_payload(silent.to_payload()) == silent
