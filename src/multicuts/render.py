"""Render semantic clip intervals and source-derived multisubs subtitles."""

from __future__ import annotations

import os
import subprocess
from math import isclose
from pathlib import Path
from typing import Protocol

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.app_config import AppConfig, RenderEncoding
from multicuts.clips import DirectClip, JudgedClip
from multicuts.errors import ConfigurationError, MediaError, RenderingError
from multicuts.media import ffmpeg_format_major, inspect_media_path
from multicuts.models import (
    AcquiredSource,
    ClipTranscript,
    ClipTranscriptSegment,
    ClipTranscriptWord,
    MediaInfo,
    SubtitleArtifacts,
    Transcript,
)
from multicuts.subtitles import SubtitleContainer, SubtitleOptions
from multicuts.variants import aspect_ratio


class SubtitleProvider(Protocol):
    def version(self) -> str: ...

    def subtitle_clip(
        self,
        video_path: Path,
        clip: ClipTranscript,
        *,
        template: str | None,
        template_dir: Path | None,
        workspace: Path,
        options: SubtitleOptions | None = None,
        container: SubtitleContainer | None = None,
        encoding: RenderEncoding | None = None,
    ) -> SubtitleArtifacts: ...


def publish_without_overwrite(temporary_path: Path, output_path: Path) -> None:
    """Hard-link complete outputs atomically and reject any existing path."""
    if output_path.exists() or output_path.is_symlink():
        raise RenderingError("render output already exists")
    try:
        os.link(temporary_path, output_path)
    except FileExistsError as exc:
        raise RenderingError("render output already exists") from exc
    except OSError as exc:
        raise RenderingError("could not publish rendered clip") from exc


def _even(value: int) -> int:
    return value - value % 2


def _crop_filter(media: MediaInfo, width: int, height: int) -> str:
    source_width = _even(media.presentation_width)
    source_height = _even(media.presentation_height)
    if source_width * height >= source_height * width:
        crop_width = _even(source_height * width // height)
        crop_height = source_height
    else:
        crop_width = source_width
        crop_height = _even(source_width * height // width)
    return (
        f"scale={source_width}:{source_height}:flags=lanczos,setsar=1,"
        f"crop={crop_width}:{crop_height}:(iw-{crop_width})/2:(ih-{crop_height})/2,"
        f"scale={width}:{height}:flags=lanczos,setsar=1"
    )


def _geometry(
    config: AppConfig, clip_class: str, media: MediaInfo
) -> tuple[str, int, int]:
    variant = config.render_variant or config.primary_for(clip_class, media)
    width, height = config.dimensions_for(clip_class, variant)
    return aspect_ratio(width, height), width, height


def foreground_dimensions(
    media: MediaInfo, variant: str, width: int, height: int
) -> tuple[int, int]:
    """Share the fitted foreground geometry between composition and captions."""
    source_width, source_height = media.presentation_width, media.presentation_height
    if variant == "vertical-blur":
        fg_ratio_width, fg_ratio_height = (
            (source_width, source_height) if source_width > source_height else (16, 9)
        )
        fg_width = width
        fg_height = max(2, _even(width * fg_ratio_height // fg_ratio_width))
    else:
        fg_ratio_width, fg_ratio_height = (
            (source_width, source_height) if source_width < source_height else (9, 16)
        )
        fg_height = height
        fg_width = max(2, _even(height * fg_ratio_width // fg_ratio_height))
    return fg_width, fg_height


def _blur_filter(media: MediaInfo, variant: str, width: int, height: int) -> str:
    fg_width, fg_height = foreground_dimensions(media, variant, width, height)
    left, top = _even((width - fg_width) // 2), _even((height - fg_height) // 2)
    return (
        f"[0:{media.video_stream_index}]"
        f"{_crop_filter(media, fg_width, fg_height)},"
        "split=2[base][fg];"
        f"[base]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={height / 36:.4f}:steps=2[bg];"
        f"[bg][fg]overlay={left}:{top}:shortest=1,setsar=1[video]"
    )


def _inspect(path: Path) -> MediaInfo:
    try:
        return inspect_media_path(path)
    except MediaError as exc:
        raise RenderingError("Could not validate rendered clip") from exc


def validate_render_encoding(config: AppConfig) -> None:
    """Check an explicit encoder on a synthetic frame before transcription."""
    if config.render_encoding.encoder is None:
        return
    encoder, preset, quality = config.render_encoding.resolved()
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        "color=s=64x64:r=1:d=1",
        "-frames:v",
        "1",
        "-c:v",
        encoder,
        "-preset",
        preset,
        "-crf" if encoder == "libx264" else "-cq",
        str(quality),
    ]
    if encoder == "h264_nvenc":
        command.extend(["-rc", "vbr", "-b:v", "0"])
    command.extend(["-f", "null", "-"])
    try:
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        if result.returncode:
            raise ConfigurationError(
                "The selected render encoder is unavailable; check FFmpeg, "
                "its encoder support, and the device/driver installation"
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigurationError(
            "Could not validate the selected render encoder"
        ) from exc


def _encode_and_publish(
    command: list[str],
    config: AppConfig,
    *,
    media: MediaInfo,
    duration: float,
    width: int,
    height: int,
    output: Path,
    work: Path,
) -> tuple[Path, MediaInfo]:
    temporary = work / f"encode-{output.stem}.mp4"
    try:
        # FFmpeg 6+ supports per-stream fps_mode; FFmpeg 9 removed vsync.
        sync_option = "-fps_mode:v" if ffmpeg_format_major() >= 60 else "-vsync"
    except MediaError as exc:
        raise RenderingError("Could not determine FFmpeg frame rate mode") from exc
    # Cuts between source frames must retain their full duration for subtitle cues.
    encoder, preset, quality = config.render_encoding.resolved()
    command.extend(
        [
            sync_option,
            "cfr",
            "-c:v",
            encoder,
            "-preset",
            preset,
            "-crf" if encoder == "libx264" else "-cq",
            str(quality),
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if encoder == "h264_nvenc":
        command.extend(["-rc", "vbr", "-b:v", "0"])
    if media.audio_stream_index is None:
        command.append("-an")
    else:
        command.extend(["-c:a", "aac", "-b:a", "128k"])
    command.extend(
        [
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            "-f",
            "mp4",
            str(temporary),
        ]
    )
    try:
        work.mkdir(parents=True, exist_ok=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(command, capture_output=True, check=False)
        if completed.returncode:
            raise RenderingError(f"FFmpeg failed with exit code {completed.returncode}")
        actual = _inspect(temporary)
        if (
            (actual.presentation_width, actual.presentation_height) != (width, height)
            or actual.has_audio != media.has_audio
            or not isclose(actual.duration, duration, rel_tol=0, abs_tol=0.25)
        ):
            raise RenderingError(
                "Rendered clip geometry, audio, or duration differs from request"
            )
        publish_without_overwrite(temporary, output)
        return output, actual
    except OSError as exc:
        raise RenderingError("Could not render or publish clip") from exc
    finally:
        if not config.keep_intermediates:
            temporary.unlink(missing_ok=True)


def render_raw(
    source: AcquiredSource,
    media: MediaInfo,
    clip: JudgedClip | DirectClip,
    config: AppConfig,
    *,
    output: Path,
    work: Path,
) -> tuple[Path, MediaInfo, str]:
    """Encode into private space and publish only a validated MP4."""
    proposal = clip.proposal
    local_start = proposal.start - source.timeline_offset
    if local_start < 0 or (
        source.acquired_range is not None and proposal.end > source.acquired_range.end
    ):
        raise RenderingError("Clip interval exceeds the acquired source interval")
    ratio, width, height = _geometry(config, proposal.clip_class, media)
    # Input seeking decodes only the keyframe lead-in while retaining accurate cuts.
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        f"{local_start:.6f}",
        "-i",
        str(source.local_path),
        "-t",
        f"{proposal.end - proposal.start:.6f}",
    ]
    if config.render_variant is not None and config.render_variant.endswith("-blur"):
        command.extend(
            [
                "-filter_complex",
                _blur_filter(media, config.render_variant, width, height),
                "-map",
                "[video]",
            ]
        )
    else:
        command.extend(
            [
                "-map",
                f"0:{media.video_stream_index}",
                "-vf",
                _crop_filter(media, width, height),
            ]
        )
    if media.audio_stream_index is not None:
        command.extend(["-map", f"0:{media.audio_stream_index}"])
    path, actual = _encode_and_publish(
        command,
        config,
        media=media,
        duration=proposal.end - proposal.start,
        width=width,
        height=height,
        output=output,
        work=work,
    )
    return path, actual, ratio


def clip_transcript(
    transcript: Transcript,
    start: float,
    end: float,
    *,
    source_duration: float | None = None,
) -> ClipTranscript:
    """Shift observed source timings into one clip without invoking ASR again."""
    duration = end - start
    segments: list[ClipTranscriptSegment] = []
    source_ranges: list[tuple[int, float, float]] = []
    for index, segment in enumerate(transcript.segments):
        if (
            segment.start is None
            or segment.end is None
            or segment.start >= end
            or segment.end < start
            or (segment.end == start and segment.start != segment.end)
        ):
            continue
        local_start = max(0.0, segment.start - start)
        local_end = min(duration, segment.end - start)
        if local_end <= local_start:
            raise ValueError("subtitle segment has no positive observed interval")
        segments.append(
            ClipTranscriptSegment(segment.text, local_start, local_end, index)
        )
        source_ranges.append((index, segment.start, segment.end))
    words: list[ClipTranscriptWord] = []
    for index, word in enumerate(transcript.words):
        if word.start is None or word.end is None:
            parent = word.source_segment_index
            if not any(segment.source_index == parent for segment in segments):
                continue
            if (word.start is not None and word.start >= end) or (
                word.end is not None and word.end <= start
            ):
                continue
            words.append(
                ClipTranscriptWord(
                    word.text,
                    None
                    if word.start is None
                    else min(duration, max(0.0, word.start - start)),
                    None
                    if word.end is None
                    else min(duration, max(0.0, word.end - start)),
                    word.confidence,
                    index,
                    parent,
                )
            )
            continue
        is_point = word.start == word.end
        if (
            is_point
            and word.source_segment_index is not None
            and not any(
                segment_id == word.source_segment_index
                for segment_id, _, _ in source_ranges
            )
        ):
            continue
        # Preserve a trailing point at the cut's end only when the provider
        # assigns it to a retained segment ending at that same observed boundary.
        trailing_point = (
            is_point
            and word.start == end
            and any(
                segment_id == word.source_segment_index and right == end
                for segment_id, _, right in source_ranges
            )
        )
        if (word.start >= end and not trailing_point) or (
            word.end < start if is_point else word.end <= start
        ):
            continue
        local_start = max(0.0, word.start - start)
        local_end = min(duration, word.end - start)
        if word.source_segment_index is not None:
            parent = next(
                (
                    segment_id
                    for segment_id, left, right in source_ranges
                    if segment_id == word.source_segment_index
                    and left <= word.end
                    and word.start <= right
                ),
                None,
            )
        elif is_point:
            # A shared boundary belongs to the following segment; retain a
            # trailing point at a segment's end when no following one contains it.
            parents = [
                segment_id
                for segment_id, left, right in source_ranges
                if left <= word.start < right
            ] or [
                segment_id
                for segment_id, left, right in source_ranges
                if left <= word.start <= right
            ]
            parent = parents[0] if parents else None
        else:
            matches = [
                (min(word.end, right) - max(word.start, left), segment_id)
                for segment_id, left, right in source_ranges
                if min(word.end, right) > max(word.start, left)
            ]
            parent = max(matches)[1] if matches else None
        words.append(
            ClipTranscriptWord(
                word.text, local_start, local_end, word.confidence, index, parent
            )
        )
    complete = (
        bool(segments and words)
        and all(
            any(word.source_segment_index == segment.source_index for word in words)
            for segment in segments
        )
        and all(word.source_segment_index is not None for word in words)
        and all(word.is_timed for word in words)
    )
    return ClipTranscript(
        language_requested=transcript.language_requested,
        language_detected=transcript.language_detected,
        duration=duration,
        source_start=start,
        source_end=end,
        source_duration=transcript.duration
        if source_duration is None
        else source_duration,
        text=" ".join(segment.text for segment in segments),
        segments=tuple(segments),
        words=tuple(words),
        provider=transcript.provider,
        provider_version=transcript.provider_version,
        word_timing_complete=complete,
        asr_backend=transcript.asr_backend,
        asr_model=transcript.asr_model,
    )


def publish_subtitle_sidecars(
    paths: tuple[Path, ...], output: Path
) -> tuple[Path, ...]:
    """Publish captions beside a video, including a privately prepared foreground."""
    published: list[Path] = []
    try:
        for path in paths:
            target = output.parent / "subtitles" / f"{output.stem}{path.suffix}"
            if path.suffix == ".json":
                target = output.parent / "subtitles" / f"{output.stem}.transcript.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            publish_without_overwrite(path, target)
            published.append(target)
    except BaseException as exc:
        for path in reversed(published):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(exc, OSError):
            raise RenderingError("Could not publish subtitle sidecars") from exc
        raise
    return tuple(published)


def render_final(
    raw_path: Path,
    raw_media: MediaInfo,
    transcript: Transcript | None,
    clip: JudgedClip | DirectClip,
    config: AppConfig,
    *,
    output: Path,
    work: Path,
    subtitle_provider: SubtitleProvider | None = None,
) -> tuple[Path, tuple[Path, ...], str | None]:
    """Publish a final clip and optional source-derived subtitle sidecars."""
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RenderingError("Could not prepare final clip directory") from exc
    if not config.subtitles_for(clip.proposal.clip_class):
        publish_without_overwrite(raw_path, output)
        return output, (), None
    if transcript is None:
        raise RenderingError("Subtitles require a source transcript")
    if config.subtitle_container is not None and (
        config.subtitle_container.frame_width != raw_media.presentation_width
        or config.subtitle_container.height != raw_media.presentation_height
    ):
        raise RenderingError("Subtitle container does not match the final canvas")
    provider = subtitle_provider or MultisubsAdapter()
    try:
        local = clip_transcript(
            transcript,
            clip.proposal.start,
            clip.proposal.end,
            source_duration=clip.source_duration
            if isinstance(clip, DirectClip)
            else None,
        )
    except ValueError as exc:
        raise RenderingError("Could not derive clip-local transcript") from exc
    artifacts = provider.subtitle_clip(
        raw_path,
        local,
        template=config.subtitle_template,
        template_dir=config.subtitle_template_dir,
        workspace=work / f"subtitles-{clip.proposal.id}",
        options=config.subtitle_options,
        container=config.subtitle_container,
        encoding=config.render_encoding
        if config.render_encoding.encoder is not None
        else None,
    )
    final_media = _inspect(artifacts.video_path)
    if (
        (final_media.presentation_width, final_media.presentation_height)
        != (raw_media.presentation_width, raw_media.presentation_height)
        or final_media.has_audio != raw_media.has_audio
        or not isclose(
            final_media.duration, raw_media.duration, rel_tol=0, abs_tol=0.25
        )
    ):
        raise RenderingError("Subtitled clip does not match validated raw clip")
    sidecars = publish_subtitle_sidecars(
        (artifacts.transcript_json_path, artifacts.srt_path, artifacts.ass_path), output
    )
    try:
        publish_without_overwrite(artifacts.video_path, output)
    except BaseException as exc:
        for path in reversed(sidecars):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(exc, OSError):
            raise RenderingError("Could not publish subtitle sidecars") from exc
        raise
    return output, sidecars, artifacts.template_resolved
