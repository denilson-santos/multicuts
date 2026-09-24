"""Safe FFmpeg boundary for rendering refined clips."""

from __future__ import annotations

import os
import re
import subprocess
from math import isclose
from pathlib import Path

from multicuts.errors import MediaError, RenderingError
from multicuts.media import inspect_media_path
from multicuts.models import MediaInfo, RenderedClip, RenderRequest

RENDERER_VERSION = "render-v1"
DEFAULT_TARGET_WIDTH = 1080
DEFAULT_TARGET_HEIGHT = 1920
_DURATION_TOLERANCE_SECONDS = 0.25
_DIAGNOSTIC_LIMIT = 2000
_SENSITIVE_FIELD = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization|cookie)\s*[:=]\s*[^\s,;]+"
)


def _even_dimension(value: int) -> int:
    """Return the largest positive even dimension not larger than ``value``."""
    result = value if value % 2 == 0 else value - 1
    if result <= 0:
        raise RenderingError("media presentation geometry is too small to render")
    return result


def expected_geometry(request: RenderRequest) -> tuple[int, int]:
    """Return the final even presentation geometry expected for a request."""
    if request.aspect_ratio == "9:16":
        return request.target_width, request.target_height
    return (
        _even_dimension(request.media.presentation_width),
        _even_dimension(request.media.presentation_height),
    )


def _expected_duration(request: RenderRequest) -> float:
    return request.refined.render_end - request.refined.render_start


def validate_rendered_media(request: RenderRequest, media: MediaInfo) -> None:
    """Validate geometry, timing, and audio of a completed temporary render."""
    expected_width, expected_height = expected_geometry(request)
    if (media.presentation_width, media.presentation_height) != (
        expected_width,
        expected_height,
    ):
        raise RenderingError(
            "rendered media geometry does not match the requested output"
        )

    expected_duration = _expected_duration(request)
    if not isclose(
        media.duration,
        expected_duration,
        rel_tol=0.0,
        abs_tol=_DURATION_TOLERANCE_SECONDS,
    ):
        raise RenderingError("rendered media duration is outside the allowed tolerance")

    if media.has_audio != request.media.has_audio:
        raise RenderingError("rendered media audio presence does not match the source")


def _center_crop_geometry(
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> tuple[int, int]:
    """Return the largest even centered crop with the target aspect ratio."""
    source_width = _even_dimension(source_width)
    source_height = _even_dimension(source_height)
    if source_width * target_height >= source_height * target_width:
        crop_width = (source_height * target_width) // target_height
        crop_height = source_height
    else:
        crop_width = source_width
        crop_height = (source_width * target_height) // target_width
    return _even_dimension(crop_width), _even_dimension(crop_height)


def _video_filter(request: RenderRequest) -> str:
    source_width = _even_dimension(request.media.presentation_width)
    source_height = _even_dimension(request.media.presentation_height)
    if request.aspect_ratio == "original":
        return f"scale={source_width}:{source_height}:flags=lanczos,setsar=1"

    crop_width, crop_height = _center_crop_geometry(
        source_width,
        source_height,
        request.target_width,
        request.target_height,
    )
    return (
        f"scale={source_width}:{source_height}:flags=lanczos,setsar=1,"
        f"crop={crop_width}:{crop_height}:(iw-{crop_width})/2:(ih-{crop_height})/2,"
        f"scale={request.target_width}:{request.target_height}:flags=lanczos,setsar=1"
    )


def _seconds(value: float) -> str:
    return f"{value:.6f}"


def build_ffmpeg_command(request: RenderRequest) -> list[str]:
    """Build the deterministic argument vector used for one raw clip."""
    duration = _expected_duration(request)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-autorotate",
        "1",
        "-i",
        str(request.source.local_path),
        "-ss",
        _seconds(request.refined.render_start),
        "-t",
        _seconds(duration),
        "-map",
        f"0:{request.media.video_stream_index}",
        "-vf",
        _video_filter(request),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
    ]
    if request.media.audio_stream_index is not None:
        command.extend(
            [
                "-map",
                f"0:{request.media.audio_stream_index}",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        )
    else:
        command.append("-an")
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
            str(request.temporary_path),
        ]
    )
    return command


def _bounded_diagnostic(value: str, request: RenderRequest | None = None) -> str:
    if request is not None:
        for path, replacement in (
            (request.source.local_path, "<source>"),
            (request.temporary_path, "<temporary>"),
            (request.output_path, "<output>"),
        ):
            for candidate in (str(path.absolute()), str(path)):
                value = value.replace(candidate, replacement)
    value = _SENSITIVE_FIELD.sub(r"\1=<redacted>", value)
    compact = " ".join(value.replace("\x00", " ").split())
    if len(compact) > _DIAGNOSTIC_LIMIT:
        return compact[:_DIAGNOSTIC_LIMIT]
    return compact


def _path_exists_including_broken_symlink(path: Path) -> bool:
    return os.path.lexists(path)


def _remove_private_path(path: Path) -> None:
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
    except OSError:
        # The original rendering failure is more useful than cleanup noise.
        pass


def publish_without_overwrite(temporary_path: Path, output_path: Path) -> None:
    """Publish by hard-linking, which is atomic and refuses existing paths."""
    if _path_exists_including_broken_symlink(output_path):
        raise RenderingError("render output already exists")
    try:
        os.link(temporary_path, output_path)
    except FileExistsError as exc:
        raise RenderingError("render output already exists") from exc
    except OSError as exc:
        raise RenderingError("could not publish rendered clip") from exc


class FfmpegRenderer:
    """Render and validate clips through FFmpeg and ffprobe."""

    def version(self) -> str:
        """Return the installed FFmpeg version line for provenance."""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RenderingError("could not determine the FFmpeg version") from exc
        if result.returncode != 0:
            raise RenderingError("could not determine the FFmpeg version")
        first_line = result.stdout.splitlines()[0].strip() if result.stdout else ""
        if not first_line:
            raise RenderingError("FFmpeg returned an empty version")
        return _bounded_diagnostic(first_line)

    def inspect(self, path: Path) -> MediaInfo:
        """Probe a local render without requiring an audio stream."""
        try:
            return inspect_media_path(path)
        except MediaError as exc:
            raise RenderingError("could not validate rendered media") from exc

    def render(self, request: RenderRequest) -> RenderedClip:
        """Render, validate, and atomically publish one refined clip."""
        source_path = request.source.local_path
        if _path_exists_including_broken_symlink(request.output_path):
            raise RenderingError("render output already exists")
        if not source_path.is_file():
            raise RenderingError("render source file is unavailable")
        if _path_exists_including_broken_symlink(request.temporary_path):
            if (
                request.temporary_path.is_dir()
                and not request.temporary_path.is_symlink()
            ):
                raise RenderingError("render temporary path is a directory")
            _remove_private_path(request.temporary_path)

        try:
            request.temporary_path.parent.mkdir(parents=True, exist_ok=True)
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RenderingError("could not prepare render paths") from exc

        command = build_ffmpeg_command(request)
        try:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            except OSError as exc:
                raise RenderingError("could not execute FFmpeg") from exc
            if result.returncode != 0:
                diagnostic = _bounded_diagnostic(
                    result.stderr or result.stdout, request
                )
                detail = f": {diagnostic}" if diagnostic else ""
                raise RenderingError(
                    f"FFmpeg failed with exit code {result.returncode}{detail}"
                )
            if not request.temporary_path.is_file():
                raise RenderingError("FFmpeg completed without producing a render")

            rendered_media = self.inspect(request.temporary_path)
            validate_rendered_media(request, rendered_media)
            publish_without_overwrite(request.temporary_path, request.output_path)
            return RenderedClip(
                refined=request.refined,
                path=request.output_path,
                width=rendered_media.presentation_width,
                height=rendered_media.presentation_height,
                duration=rendered_media.duration,
                has_audio=rendered_media.has_audio,
                renderer_version=request.renderer_version,
                cache_key=request.cache_key,
            )
        except RenderingError:
            raise
        except OSError as exc:
            raise RenderingError("rendering failed") from exc
        finally:
            _remove_private_path(request.temporary_path)
