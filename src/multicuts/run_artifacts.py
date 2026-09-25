"""Collect final run documents from normalized pipeline results."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from math import isclose
from pathlib import Path

from multicuts.artifacts import WorkspacePaths
from multicuts.candidates.ranking import SELECTION_ALGORITHM_VERSION
from multicuts.config import RunConfig
from multicuts.errors import ArtifactError, RenderingError
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
)
from multicuts.models import (
    AcquiredSource,
    CandidateEvaluationArtifact,
    MediaInfo,
    RefinedSelection,
    RenderedClip,
    ScoringBatch,
    SelectionResult,
    Transcript,
)
from multicuts.rendering.subtitle_artifacts import template_directory_sha256
from multicuts.transcripts import derive_clip_transcript

_SAFE_CODE = re.compile(r"[a-z][a-z0-9_:-]*\Z")


def collect_clip_metadata(
    paths: WorkspacePaths,
    config: RunConfig,
    transcript: Transcript,
    raw: RenderedClip,
    final_path: Path,
    *,
    inspect: Callable[[Path], MediaInfo],
) -> ClipMetadata:
    """Use the validated final media and its subtitle record as the source of truth."""
    if final_path.parent != paths.root / "clips" or final_path.suffix != ".mp4":
        raise ArtifactError("Final clip is outside the run clips directory")
    if (
        final_path.is_symlink()
        or not final_path.is_file()
        or final_path.stat().st_size <= 0
    ):
        raise ArtifactError("Final clip media is missing or incomplete")
    try:
        media = inspect(final_path)
    except RenderingError as exc:
        raise ArtifactError("Could not validate final clip media") from exc
    if (
        (media.presentation_width, media.presentation_height) != (raw.width, raw.height)
        or media.has_audio != raw.has_audio
        or not isclose(media.duration, raw.duration, rel_tol=0, abs_tol=0.25)
    ):
        raise ArtifactError("Final clip media does not match its raw render")

    stage_metadata = paths.rendering / "subtitles" / f"{final_path.stem}.json"
    try:
        stage_record = json.loads(stage_metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("Final clip stage metadata is unavailable") from exc
    if (
        not isinstance(stage_record, dict)
        or stage_record.get("filename") != final_path.name
        or stage_record.get("candidate_id") != raw.refined.candidate_id
        or stage_record.get("duration") != media.duration
        or stage_record.get("subtitles_enabled") != config.subtitles_enabled
    ):
        raise ArtifactError("Final clip stage metadata does not match validated media")
    resolved = stage_record.get("template_resolved")
    provider_version = stage_record.get("provider_version")
    if config.subtitles_enabled and (
        not isinstance(resolved, str)
        or not resolved.strip()
        or not isinstance(provider_version, str)
        or not provider_version.strip()
    ):
        raise ArtifactError("Final subtitle provenance is incomplete")
    if not config.subtitles_enabled:
        resolved = None
        provider_version = None

    selected = raw.refined.selected
    candidate = selected.evaluation.candidate
    title, summary = derive_clip_title_summary(candidate.text)
    clip_transcript = derive_clip_transcript(transcript, raw.refined)
    return ClipMetadata(
        schema_version=FINAL_ARTIFACT_SCHEMA_VERSION,
        id=selected.candidate_id,
        rank=selected.rank,
        source_start=candidate.start,
        source_end=candidate.end,
        render_start=raw.refined.render_start,
        render_end=raw.refined.render_end,
        duration=media.duration,
        title=title,
        summary=summary,
        candidate_text=candidate.text,
        score=selected.result,
        checklist=selected.evaluation.checklist,
        transcript=clip_transcript.text,
        render_config=ClipRenderSettings(
            aspect_ratio=config.aspect_ratio,
            width=media.presentation_width,
            height=media.presentation_height,
            subtitles_enabled=config.subtitles_enabled,
            template_requested=(
                config.subtitle_template if config.subtitles_enabled else None
            ),
            template_resolved=resolved,
            multisubs_version=provider_version,
        ),
        output_path=final_path.relative_to(paths.root).as_posix(),
    )


def collect_run_manifest(
    config: RunConfig,
    source: AcquiredSource,
    transcript: Transcript,
    evaluation: CandidateEvaluationArtifact,
    generated_count: int,
    scoring: ScoringBatch,
    selection: SelectionResult,
    refined: tuple[RefinedSelection, ...],
    raw_clips: tuple[RenderedClip, ...],
    references: tuple[ClipReference, ...],
    timings: tuple[StageTiming, ...],
    *,
    run_id: str,
    created_at: str,
) -> RunManifest:
    """Summarize observed stages and published or rejected clip results."""
    if tuple(item.candidate_id for item in refined) != tuple(
        item.candidate_id for item in selection.selected
    ):
        raise ArtifactError("Refinement does not match selected clips")
    if scoring.provenance.mode != config.scorer:
        raise ArtifactError("Scoring provenance does not match run configuration")
    by_id = {item.id: item for item in references}
    for item in refined:
        if item.candidate_id not in by_id:
            raise ArtifactError("Selected clip has no final artifact outcome")
    completed = sum(item.status is ClipOutcome.COMPLETED for item in references)
    failed = len(references) - completed
    if completed and failed:
        outcome = RunOutcome.PARTIAL
    elif completed:
        outcome = RunOutcome.COMPLETED
    elif references:
        outcome = RunOutcome.FAILED
    else:
        outcome = RunOutcome.ZERO_SELECTION

    heuristic = sum(item.result.scorer == "heuristic" for item in scoring.scores)
    hybrid = sum(item.result.scorer == "hybrid" for item in scoring.scores)
    fallback = sum(
        item.result.scorer == "heuristic-fallback" for item in scoring.scores
    )
    versions = {item.result.scoring_algorithm_version for item in scoring.scores}
    hybrid_score = next(
        (item.result for item in scoring.scores if item.result.scorer == "hybrid"),
        None,
    )
    warnings = tuple(
        f"semantic_failure:{failure.code}"
        if _SAFE_CODE.fullmatch(failure.code)
        else "semantic_failure:unknown"
        for failure in scoring.failures
    )
    if any(item.requires_rescore for item in refined):
        warnings += ("refinement_requires_rescore",)
    ffmpeg_versions = {item.renderer_version for item in raw_clips}
    if len(ffmpeg_versions) > 1:
        raise ArtifactError("Rendered clips disagree on FFmpeg version")
    try:
        settings = RunSettings.from_config(
            config,
            template_directory_sha256=template_directory_sha256(
                config.subtitle_template_dir if config.subtitles_enabled else None
            ),
        )
    except ValueError as exc:
        raise ArtifactError("Run configuration cannot be recorded safely") from exc

    try:
        source_reference = SourceReference.from_source(source)
        package_version = version("multicuts")
    except (ValueError, PackageNotFoundError) as exc:
        raise ArtifactError("Run provenance cannot be recorded safely") from exc

    return RunManifest(
        schema_version=FINAL_ARTIFACT_SCHEMA_VERSION,
        run_id=run_id,
        created_at=created_at,
        outcome=outcome,
        source=source_reference,
        source_fingerprint=source.fingerprint,
        config=settings,
        versions=RunVersions(
            multicuts=package_version,
            multisubs=transcript.provider_version,
            ffmpeg=next(iter(ffmpeg_versions), None),
        ),
        transcription=StageSummary("completed", 1, transcript.provider_version),
        candidate_generation=StageSummary(
            "completed",
            generated_count,
            evaluation.candidate_generator_version,
        ),
        scoring=ScoringSummary(
            status="completed",
            count=len(scoring.scores),
            configured_mode=config.scorer,
            heuristic_count=heuristic,
            hybrid_count=hybrid,
            fallback_count=fallback,
            provider=hybrid_score.provider if hybrid_score else None,
            model=hybrid_score.model if hybrid_score else None,
            scorer_version=next(iter(versions)) if len(versions) == 1 else None,
        ),
        selection=StageSummary(
            "completed", len(selection.selected), SELECTION_ALGORITHM_VERSION
        ),
        clips=references,
        timings=timings,
        warnings=warnings,
    )
