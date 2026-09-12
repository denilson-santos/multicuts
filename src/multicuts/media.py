"""FFprobe boundary and normalized media geometry."""

import json
import subprocess
from math import isclose, isfinite

from multicuts.errors import MediaError
from multicuts.models import AcquiredSource, MediaInfo


def probe_media(source: AcquiredSource) -> MediaInfo:
    """Inspect a local source with ffprobe and return project-owned metadata."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(source.local_path),
    ]
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
        raise MediaError("Could not run ffprobe") from exc

    if result.returncode != 0:
        # Provider diagnostics may contain user paths or metadata.
        raise MediaError(f"ffprobe failed (exit code {result.returncode})")
    try:
        payload: object = json.loads(result.stdout)
    except ValueError as exc:
        raise MediaError("ffprobe returned invalid JSON") from exc
    return normalize_media_probe(payload)


def normalize_media_probe(payload: object) -> MediaInfo:
    """Convert the ffprobe JSON fields needed by the pipeline into `MediaInfo`."""
    if not isinstance(payload, dict):
        raise MediaError("ffprobe result must be an object")
    streams = payload.get("streams")
    media_format = payload.get("format")
    if not isinstance(streams, list) or not isinstance(media_format, dict):
        raise MediaError("ffprobe result is missing streams or format")
    if any(not isinstance(stream, dict) for stream in streams):
        raise MediaError("ffprobe stream data is invalid")

    duration = _positive_float(media_format.get("duration"))
    if duration is None:
        raise MediaError("Media duration is missing or invalid")

    video = _select_video_stream(streams)
    audio_index = _select_audio_stream_index(streams)
    width = _nonnegative_int(video.get("width"))
    height = _nonnegative_int(video.get("height"))
    video_index = _nonnegative_int(video.get("index"))
    if width is None or height is None or video_index is None:
        raise MediaError("Video stream geometry is invalid")

    sample_aspect = _sample_aspect_ratio(video.get("sample_aspect_ratio"))
    rotation = _rotation_degrees(video)
    # Integer rounding avoids losing precision for unusual sample aspect ratios.
    presentation_width = (2 * width * sample_aspect[0] + sample_aspect[1]) // (
        2 * sample_aspect[1]
    )
    presentation_height = height
    if presentation_width <= 0:
        raise MediaError("Presentation geometry is invalid")

    quarter_turns = round(rotation / 90)
    if not isclose(rotation, quarter_turns * 90, rel_tol=0, abs_tol=0.01):
        raise MediaError("Media rotation is not a supported quarter turn")
    if quarter_turns % 2:
        presentation_width, presentation_height = (
            presentation_height,
            presentation_width,
        )

    try:
        return MediaInfo(
            duration=duration,
            coded_width=width,
            coded_height=height,
            presentation_width=presentation_width,
            presentation_height=presentation_height,
            video_stream_index=video_index,
            audio_stream_index=audio_index,
            rotation_degrees=rotation,
        )
    except ValueError as exc:
        raise MediaError("Media stream metadata is invalid") from exc


def _select_video_stream(streams: list[object]) -> dict[str, object]:
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("codec_type") != "video":
            continue
        disposition = stream.get("disposition")
        if isinstance(disposition, dict) and disposition.get("attached_pic") == 1:
            continue
        width = _nonnegative_int(stream.get("width"))
        height = _nonnegative_int(stream.get("height"))
        index = _nonnegative_int(stream.get("index"))
        if width is not None and width > 0 and height is not None and height > 0:
            if index is not None:
                return stream
    raise MediaError("No usable video stream found")


def _select_audio_stream_index(streams: list[object]) -> int | None:
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("codec_type") != "audio":
            continue
        index = _nonnegative_int(stream.get("index"))
        channels = _nonnegative_int(stream.get("channels"))
        sample_rate = _nonnegative_int(stream.get("sample_rate"))
        if (
            index is not None
            and channels is not None
            and channels > 0
            and sample_rate is not None
            and sample_rate > 0
        ):
            return index
    return None


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except (ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) and parsed > 0 else None


def _sample_aspect_ratio(value: object) -> tuple[int, int]:
    if value is None or value == "N/A":
        return (1, 1)
    if not isinstance(value, str):
        raise MediaError("Sample aspect ratio is invalid")
    parts = value.split(":")
    if len(parts) != 2:
        raise MediaError("Sample aspect ratio is invalid")
    numerator = _nonnegative_int(parts[0])
    denominator = _nonnegative_int(parts[1])
    if numerator is None or denominator is None or numerator == 0 or denominator == 0:
        raise MediaError("Sample aspect ratio is invalid")
    return numerator, denominator


def _rotation_degrees(stream: dict[str, object]) -> float:
    side_data = stream.get("side_data_list")
    if side_data is not None:
        if not isinstance(side_data, list):
            raise MediaError("Video rotation metadata is invalid")
        for item in side_data:
            if isinstance(item, dict) and "rotation" in item:
                return _finite_rotation(item["rotation"])
    tags = stream.get("tags")
    if tags is not None:
        if not isinstance(tags, dict):
            raise MediaError("Video rotation metadata is invalid")
        if "rotate" in tags:
            return _finite_rotation(tags["rotate"])
    return 0.0


def _finite_rotation(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MediaError("Video rotation metadata is invalid")
    try:
        rotation = float(value)
    except (ValueError, OverflowError) as exc:
        raise MediaError("Video rotation metadata is invalid") from exc
    if not isfinite(rotation):
        raise MediaError("Video rotation metadata is invalid")
    return rotation
