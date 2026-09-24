"""Validate and safely publish hard-subtitled final clips."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from math import isclose
from pathlib import Path
from typing import Protocol

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.adapters.multisubs_subtitles import SubtitleArtifacts
from multicuts.errors import MediaError, RenderingError, TranscriptionError
from multicuts.media import inspect_media_path
from multicuts.models import ClipTranscript, MediaInfo, RenderedClip
from multicuts.rendering.cutter import publish_without_overwrite

_DURATION_TOLERANCE_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class SubtitledClip:
    """Validated final video and its source-derived subtitle artifacts."""

    raw: RenderedClip
    path: Path
    width: int
    height: int
    duration: float
    has_audio: bool
    subtitles: SubtitleArtifacts


def _validate_media(media: MediaInfo, raw: RenderedClip, *, stage: str) -> None:
    if (media.presentation_width, media.presentation_height) != (
        raw.width,
        raw.height,
    ):
        raise RenderingError(f"{stage} clip geometry does not match the raw render")
    if not isclose(
        media.duration,
        raw.duration,
        rel_tol=0.0,
        abs_tol=_DURATION_TOLERANCE_SECONDS,
    ):
        raise RenderingError(f"{stage} clip duration does not match the raw render")
    if media.has_audio != raw.has_audio:
        raise RenderingError(
            f"{stage} clip audio presence does not match the raw render"
        )


class SubtitleProvider(Protocol):
    """Public subtitle operation required by the rendering coordinator."""

    def version(self) -> str: ...

    def subtitle_clip(
        self,
        video_path: Path,
        clip: ClipTranscript,
        *,
        template: str | None,
        template_dir: Path | None,
        workspace: Path,
    ) -> SubtitleArtifacts: ...


class SubtitleRenderer:
    """Coordinate public multisubs rendering after raw final-geometry rendering."""

    def __init__(self, adapter: SubtitleProvider | None = None) -> None:
        self.adapter = adapter or MultisubsAdapter()

    def version(self) -> str:
        """Return the multisubs version used in subtitle cache identity."""
        try:
            return self.adapter.version()
        except TranscriptionError as exc:
            raise RenderingError(
                "multisubs is unavailable for subtitle rendering"
            ) from exc

    def inspect(self, path: Path) -> MediaInfo:
        try:
            return inspect_media_path(path)
        except MediaError as exc:
            raise RenderingError(
                f"Could not validate subtitle video: {path.name}"
            ) from exc

    def render(
        self,
        raw: RenderedClip,
        clip: ClipTranscript,
        *,
        output_path: Path,
        workspace: Path,
        template: str | None,
        template_dir: Path | None,
    ) -> SubtitledClip:
        """Render against the raw clip and publish only a validated final video."""
        if not isinstance(raw, RenderedClip) or not isinstance(clip, ClipTranscript):
            raise RenderingError("Subtitles require a rendered clip and ClipTranscript")
        if not isinstance(output_path, Path) or not isinstance(workspace, Path):
            raise RenderingError("Subtitle output and workspace must be paths")
        if (
            clip.source_start != raw.refined.render_start
            or clip.source_end != raw.refined.render_end
            or not isclose(
                clip.duration,
                raw.duration,
                rel_tol=0.0,
                abs_tol=_DURATION_TOLERANCE_SECONDS,
            )
        ):
            raise RenderingError(
                "Clip transcript does not match the raw render interval"
            )
        if not raw.path.is_file():
            raise RenderingError("Raw clip is unavailable for subtitle rendering")
        if output_path.resolve(strict=False) == raw.path.resolve(strict=False):
            raise RenderingError("Final subtitle output must differ from the raw clip")
        if output_path.resolve(strict=False).is_relative_to(
            workspace.resolve(strict=False)
        ):
            raise RenderingError(
                "Final subtitle output must be outside the private workspace"
            )
        if os.path.lexists(output_path):
            raise RenderingError("Final subtitle output already exists")

        actual_raw = self.inspect(raw.path)
        _validate_media(actual_raw, raw, stage="Raw")
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RenderingError(
                "Could not prepare final subtitle output directory"
            ) from exc

        artifacts = self.adapter.subtitle_clip(
            raw.path,
            clip,
            template=template,
            template_dir=template_dir,
            workspace=workspace,
        )
        final_media = self.inspect(artifacts.video_path)
        _validate_media(final_media, raw, stage="Subtitled")
        if not isclose(
            final_media.duration,
            actual_raw.duration,
            rel_tol=0.0,
            abs_tol=_DURATION_TOLERANCE_SECONDS,
        ):
            raise RenderingError(
                "Subtitled clip duration drifted from the probed raw clip"
            )
        publish_without_overwrite(artifacts.video_path, output_path)
        return SubtitledClip(
            raw=raw,
            path=output_path,
            width=final_media.presentation_width,
            height=final_media.presentation_height,
            duration=final_media.duration,
            has_audio=final_media.has_audio,
            subtitles=replace(artifacts, video_path=output_path),
        )
