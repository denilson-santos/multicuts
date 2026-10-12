"""FFprobe boundary and normalized media geometry."""

import json
import os
import re
import subprocess
import tempfile
from dataclasses import replace
from hashlib import sha256
from math import ceil, isclose, isfinite
from pathlib import Path

from multicuts.errors import MediaError
from multicuts.models import AcquiredSource, MediaInfo, TimeRange


def check_media_tools() -> None:
    """Verify that both runtime media tools can start before probing a source."""
    for tool in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run(
                [tool, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=5,
            )
        except FileNotFoundError as exc:
            raise MediaError(
                f"{tool} is unavailable; install FFmpeg and add it to PATH"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaError(
                f"{tool} version check timed out; check the FFmpeg installation"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise MediaError(
                f"{tool} version check failed (exit code {exc.returncode}); "
                "check the FFmpeg installation"
            ) from exc
        except OSError as exc:
            raise MediaError(
                f"Could not run {tool}; check the FFmpeg installation and PATH"
            ) from exc


def probe_media(source: AcquiredSource) -> MediaInfo:
    """Inspect a source and require the audio needed for transcription."""
    media = inspect_media_path(source.local_path)
    validate_media_for_transcription(media)
    return media


def inspect_media_path(path: Path) -> MediaInfo:
    """Inspect local media with ffprobe without imposing ASR audio requirements."""
    check_media_tools()
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-show_data",
        "-of",
        "json",
        str(path),
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
        raise MediaError(
            "Could not inspect media with ffprobe; "
            "check the installation and source permissions"
        ) from exc

    if result.returncode != 0:
        # Provider diagnostics may contain user paths or metadata.
        raise MediaError(
            f"Could not inspect media with ffprobe (exit code {result.returncode}); "
            "check that the source is a supported video"
        )
    try:
        payload: object = json.loads(result.stdout)
    except ValueError as exc:
        raise MediaError("ffprobe returned invalid JSON") from exc
    return normalize_media_probe(payload)


def validate_media_for_transcription(media: MediaInfo) -> None:
    """Reject normalized media that cannot provide audio for transcription."""
    if not media.has_audio:
        raise MediaError("No usable audio stream found; source cannot be transcribed")


def prepare_source_range(
    source: AcquiredSource,
    media: MediaInfo,
    interval: TimeRange,
    workspace: Path,
) -> tuple[AcquiredSource, MediaInfo]:
    """Copy a shared range source, retaining keyframe padding and its real offset."""
    validate_media_for_transcription(media)
    original_duration = source.original_duration or media.duration
    if interval.end > original_duration:
        raise MediaError("Requested interval exceeds source media duration")
    check_media_tools()
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        # MP4/MOV retain display-matrix rotation; Matroska accepts the other
        # source codecs without selecting a lossy fallback encoder.
        suffix = source.local_path.suffix.lower()
        suffix = suffix if suffix in {".mp4", ".mov"} else ".mkv"
        output = workspace / source.local_path.with_suffix(suffix).name
        with tempfile.TemporaryDirectory(dir=workspace) as private:
            raw_path = source.local_path
            raw_media = media
            if source.acquired_range is None:
                raw_path = Path(private) / f"source-timestamps{suffix}"
                _copy_media(source.local_path, raw_path, media, interval=interval)
                raw_media = inspect_media_path(raw_path)
            # The first copy keeps source timestamps, so the preceding keyframe
            # never becomes an unrecorded shift. Normalize only after probing it.
            start = max(0.0, raw_media.start_time)
            normalized = Path(private) / f"normalized{suffix}"
            # yt-dlp's Matroska download also remuxes Opus once; compensate
            # that codec-delay subtraction as well as this normalization pass.
            extra_audio_delay = (
                raw_media.audio_codec_delay
                if source.source_kind == "youtube"
                and raw_path.suffix.lower() in {".webm", ".mkv"}
                else 0.0
            )
            _copy_media(
                raw_path, normalized, raw_media, extra_audio_delay=extra_audio_delay
            )
            prepared_media = inspect_media_path(normalized)
            validate_media_for_transcription(prepared_media)
            if abs(prepared_media.start_time) > 0.001:
                raise MediaError("Copied source timeline could not be normalized")
            end = min(original_duration, start + prepared_media.duration)
            if start > interval.start + 0.001 or end < interval.end - 0.001:
                raise MediaError("Copied source does not cover the requested interval")
            if (
                prepared_media.presentation_width != media.presentation_width
                or prepared_media.presentation_height != media.presentation_height
            ):
                raise MediaError("Copied source changed presentation geometry")
            acquired_range = TimeRange(start, end)
            identity = json.dumps(
                [
                    source.fingerprint,
                    float(interval.start),
                    float(interval.end),
                    start,
                    end,
                    "stream-copy-v2",
                ],
                separators=(",", ":"),
            )
            prepared_source = replace(
                source,
                local_path=output,
                fingerprint="sha256-v1:" + sha256(identity.encode("utf-8")).hexdigest(),
                acquired_range=acquired_range,
                original_duration=original_duration,
            )
            os.link(normalized, output)
        return prepared_source, prepared_media
    except OSError as exc:
        raise MediaError("Could not prepare the source interval") from exc


def ffmpeg_format_major() -> int:
    """Read the libavformat major version from the installed FFmpeg binary."""
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
        raise MediaError("Could not determine FFmpeg libavformat version") from exc
    match = re.search(r"^libavformat\s+(\d+)\.", result.stdout, re.MULTILINE)
    if result.returncode or match is None:
        raise MediaError("Could not determine FFmpeg libavformat version")
    return int(match.group(1))


def _copy_media(
    source: Path,
    output: Path,
    media: MediaInfo,
    *,
    interval: TimeRange | None = None,
    extra_audio_delay: float = 0.0,
) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if interval is not None:
        if interval.start:
            command += ["-ss", f"{interval.start:.6f}"]
        command += ["-t", f"{interval.end - interval.start:.6f}"]
    command += ["-i", str(source), "-map", f"0:{media.video_stream_index}"]
    if media.audio_stream_index is not None:
        command += ["-map", f"0:{media.audio_stream_index}"]
    command += [
        "-c",
        "copy",
        "-copyts",
        "-start_at_zero",
        "-avoid_negative_ts",
        "disabled",
    ]
    if (
        output.suffix == ".mkv"
        and media.audio_codec_delay
        # libavformat 60 (FFmpeg 6.0) restores initial padding natively.
        and ffmpeg_format_major() < 60
    ):
        delay = media.audio_codec_delay + extra_audio_delay
        if extra_audio_delay:
            # Each Matroska mux pass rounds CodecDelay to millisecond ticks.
            delay = (
                ceil(media.audio_codec_delay * 1000) + ceil(extra_audio_delay * 1000)
            ) / 1000
        # Older Matroska muxers subtract CodecDelay when remuxing Opus. Restore
        # packet timestamps without changing encoded audio or its pre-skip header.
        command += ["-bsf:a", f"setts=pts=PTS+{delay:.9f}/TB:dts=DTS+{delay:.9f}/TB"]
    command += ["-y", str(output)]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise MediaError(
            "Could not copy the source interval with FFmpeg "
            f"(exit code {result.returncode}); source streams must support remuxing"
        )


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
            start_time=_media_start_time(media_format.get("start_time", "0")),
            audio_codec_delay=_audio_codec_delay(streams, audio_index),
        )
    except ValueError as exc:
        raise MediaError("Media stream metadata is invalid") from exc


def _media_start_time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MediaError("Media start time is invalid")
    try:
        start = float(value)
    except (ValueError, OverflowError) as exc:
        raise MediaError("Media start time is invalid") from exc
    if not isfinite(start):
        raise MediaError("Media start time is invalid")
    return start


def _audio_codec_delay(streams: list[object], index: int | None) -> float:
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("index") != index:
            continue
        if stream.get("codec_name") != "opus":
            return 0.0
        data = stream.get("extradata")
        if not isinstance(data, str):
            raise MediaError("Opus codec delay metadata is missing")
        try:
            header = bytes.fromhex(
                "".join(
                    line.split(":", 1)[1].split("  ", 1)[0].replace(" ", "")
                    for line in data.splitlines()
                    if ":" in line
                )
            )
        except ValueError as exc:
            raise MediaError("Opus codec delay metadata is invalid") from exc
        if len(header) < 12 or header[:8] != b"OpusHead":
            raise MediaError("Opus codec delay metadata is invalid")
        return int.from_bytes(header[10:12], "little") / 48000
    return 0.0


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
