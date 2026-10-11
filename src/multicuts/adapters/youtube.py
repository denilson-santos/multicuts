"""yt-dlp boundary for one controlled YouTube download."""

import json
import re
from hashlib import sha256
from math import isclose, isfinite
from pathlib import Path
from typing import Protocol, cast

from multicuts.errors import AcquisitionError, ConfigurationError, MediaError
from multicuts.media import check_media_tools
from multicuts.models import AcquiredSource, TimeRange
from multicuts.source import parse_youtube_url

try:
    from yt_dlp import YoutubeDL
except ImportError:  # pragma: no cover - exercised only in incomplete installs
    YoutubeDL = None  # type: ignore[assignment,misc]

YOUTUBE_FINGERPRINT_VERSION = "youtube-sha256-v1"
YOUTUBE_PROVIDER = "youtube"
_HASH_CHUNK_SIZE = 1024 * 1024
_MAX_TITLE_LENGTH = 500
_MAX_PROVIDER_ID_LENGTH = 200
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


class _Downloader(Protocol):
    def __enter__(self) -> "_Downloader": ...

    def __exit__(self, *args: object) -> None: ...

    def extract_info(self, url: str, download: bool = True) -> object: ...

    def prepare_filename(self, info_dict: object) -> str: ...


class _DownloaderFactory(Protocol):
    def __call__(self, options: dict[str, object]) -> _Downloader: ...


def _safe_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(_CONTROL_CHARACTER_PATTERN.sub(" ", value).split())
    if not normalized:
        return None
    return normalized[:limit].rstrip()


def _safe_provider_id(value: object) -> str | None:
    normalized = _safe_text(value, limit=_MAX_PROVIDER_ID_LENGTH)
    if normalized is None or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in normalized
    ):
        return None
    return normalized


def _workspace_path(workspace: Path) -> Path:
    if not isinstance(workspace, Path):
        raise AcquisitionError("YouTube acquisition workspace must be a Path")
    try:
        resolved = workspace.expanduser().resolve(strict=False)
        resolved.mkdir(parents=True, exist_ok=True)
        resolved = resolved.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AcquisitionError(
            "Could not prepare the YouTube download workspace"
        ) from exc
    if not resolved.is_dir():
        raise AcquisitionError("YouTube download workspace is not a directory")
    return resolved


def _options(workspace: Path, time_range: TimeRange | None) -> dict[str, object]:
    temporary = workspace / ".tmp"
    try:
        temporary.mkdir(exist_ok=True)
        resolved_temporary = temporary.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AcquisitionError(
            "Could not prepare the YouTube temporary workspace"
        ) from exc
    if not resolved_temporary.is_dir() or not resolved_temporary.is_relative_to(
        workspace
    ):
        raise AcquisitionError("YouTube temporary workspace escapes its root")
    options: dict[str, object] = {
        "format": "bestvideo*+bestaudio/best",
        "outtmpl": str(workspace / "%(id)s.%(ext)s"),
        "paths": {"home": str(workspace), "temp": str(temporary)},
        "merge_output_format": "mp4",
        "noplaylist": True,
        "overwrites": False,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }
    if time_range is not None:

        def download_ranges(
            info: object, _downloader: object
        ) -> list[dict[str, float]]:
            _range_duration(_raw_mapping(info), time_range)
            return [{"start_time": time_range.start, "end_time": time_range.end}]

        options["download_ranges"] = download_ranges
        options["force_keyframes_at_cuts"] = True
    return options


def _range_duration(info: dict[str, object], time_range: TimeRange) -> float:
    duration = info.get("duration")
    if (
        info.get("is_live")
        or info.get("live_status") in ("is_live", "is_upcoming", "post_live")
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not isfinite(duration)
        or duration <= 0
    ):
        raise AcquisitionError(
            "YouTube interval downloads require a completed video with known duration"
        )
    if time_range.end > duration:
        raise ConfigurationError("Requested interval exceeds source media duration")
    return float(duration)


def _validate_downloaded_range(info: dict[str, object], time_range: TimeRange) -> None:
    downloads = info.get("requested_downloads")
    if not isinstance(downloads, list) or len(downloads) != 1:
        raise AcquisitionError("YouTube did not return the requested single interval")
    section = _raw_mapping(downloads[0])
    for name, expected in (
        ("section_start", time_range.start),
        ("section_end", time_range.end),
    ):
        value = section.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or not isclose(value, expected, rel_tol=0, abs_tol=0.000001)
        ):
            raise AcquisitionError("YouTube returned an unexpected download interval")


def _raw_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AcquisitionError("YouTube returned malformed source metadata")
    return cast(dict[str, object], value)


def _validate_optional_metadata(info: dict[str, object]) -> None:
    for field_name in ("duration", "width", "height"):
        value = info.get(field_name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AcquisitionError("YouTube returned malformed media metadata")
        if not isfinite(value) or value <= 0:
            raise AcquisitionError("YouTube returned malformed media metadata")
    for field_name in ("format_id", "ext", "vcodec", "acodec"):
        value = info.get(field_name)
        if value is not None and _safe_text(value, limit=200) is None:
            raise AcquisitionError("YouTube returned malformed media metadata")


def _candidate_paths(
    info: dict[str, object], downloader: _Downloader, workspace: Path
) -> tuple[Path, ...]:
    values: list[object] = []
    for key in ("filepath", "_filename"):
        if key in info:
            values.append(info[key])
    requested = info.get("requested_downloads")
    if isinstance(requested, list):
        for item in requested:
            if isinstance(item, dict) and "filepath" in item:
                values.append(item["filepath"])
    try:
        values.append(downloader.prepare_filename(info))
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    source_id = _safe_provider_id(info.get("id"))
    extensions = [_safe_text(info.get("ext"), limit=20), "mp4", "webm", "mkv"]
    if source_id is not None:
        values.extend(
            workspace / f"{source_id}.{extension}"
            for extension in extensions
            if extension is not None
        )

    candidates: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            candidate = Path(value).expanduser()
        except (OSError, RuntimeError, ValueError):
            continue
        if not candidate.is_absolute():
            candidate = workspace / candidate
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _downloaded_path(
    info: dict[str, object], downloader: _Downloader, workspace: Path
) -> Path:
    for candidate in _candidate_paths(info, downloader, workspace):
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_file():
            continue
        if not resolved.is_relative_to(workspace):
            raise AcquisitionError(
                "YouTube downloader returned a path outside its workspace"
            )
        return resolved
    raise AcquisitionError("YouTube download completed without a usable media file")


def _hash_file(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as media_file:
            while chunk := media_file.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
    except OSError as exc:
        raise AcquisitionError("Downloaded YouTube media cannot be read") from exc
    return digest.hexdigest()


def _optional_identity_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not isfinite(value):
            return None
        return value
    return None


def _fingerprint(
    *,
    info: dict[str, object],
    media_path: Path,
    source_id: str,
    time_range: TimeRange | None = None,
) -> str:
    identity = {
        "provider": YOUTUBE_PROVIDER,
        "source_id": source_id,
        "media_sha256": _hash_file(media_path),
        "format_id": _optional_identity_value(info.get("format_id")),
        "ext": _safe_text(info.get("ext"), limit=20),
        "duration": _optional_identity_value(info.get("duration")),
        "width": _optional_identity_value(info.get("width")),
        "height": _optional_identity_value(info.get("height")),
        "vcodec": _safe_text(info.get("vcodec"), limit=80),
        "acodec": _safe_text(info.get("acodec"), limit=80),
    }
    if time_range is not None:
        identity["acquired_range"] = {
            "start": float(time_range.start),
            "end": float(time_range.end),
        }
    canonical = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return (
        f"{YOUTUBE_FINGERPRINT_VERSION}:{sha256(canonical.encode('utf-8')).hexdigest()}"
    )


def _normalize_result(
    info_value: object,
    downloader: _Downloader,
    workspace: Path,
    source: str,
    time_range: TimeRange | None = None,
) -> AcquiredSource:
    info = _raw_mapping(info_value)
    if info.get("_type") in {"playlist", "multi_video"} or "entries" in info:
        raise AcquisitionError("YouTube playlists and batches are not supported")
    source_id = _safe_provider_id(info.get("id"))
    title = _safe_text(info.get("title"), limit=_MAX_TITLE_LENGTH)
    if source_id is None or title is None:
        raise AcquisitionError("YouTube returned incomplete source metadata")
    _validate_optional_metadata(info)
    original_duration = None
    if time_range is not None:
        original_duration = _range_duration(info, time_range)
        _validate_downloaded_range(info, time_range)
    reference = parse_youtube_url(source)
    if reference is None:
        raise AcquisitionError("YouTube source URL is invalid")
    original_url = reference.canonical_url
    media_path = _downloaded_path(info, downloader, workspace)
    try:
        fingerprint = _fingerprint(
            info=info,
            media_path=media_path,
            source_id=source_id,
            time_range=time_range,
        )
        return AcquiredSource(
            local_path=media_path,
            fingerprint=fingerprint,
            source_kind="youtube",
            provider_id=source_id,
            title=title,
            original_url=original_url,
            acquired_range=time_range,
            original_duration=original_duration,
        )
    except ValueError as exc:
        raise AcquisitionError("YouTube source metadata is invalid") from exc


class YoutubeAdapter:
    """Acquire one supported YouTube URL with yt-dlp's Python API."""

    def acquire(
        self, source: str, workspace: Path, *, time_range: TimeRange | None = None
    ) -> AcquiredSource:
        reference = parse_youtube_url(source)
        if reference is None:
            raise AcquisitionError("Source is not a supported YouTube URL")
        if YoutubeDL is None:
            raise AcquisitionError(
                "yt-dlp is unavailable; install the YouTube acquisition dependency"
            )
        if time_range is not None:
            check_media_tools()
        resolved_workspace = _workspace_path(workspace)
        options = _options(resolved_workspace, time_range)
        try:
            downloader_factory = cast(_DownloaderFactory, YoutubeDL)
            with downloader_factory(options) as downloader:
                info = downloader.extract_info(source, download=True)
                return _normalize_result(
                    info, downloader, resolved_workspace, source, time_range
                )
        except (AcquisitionError, ConfigurationError, MediaError):
            raise
        except Exception:
            # Provider exceptions frequently include signed URLs or cookies.
            # Suppress the provider diagnostic so it cannot reach a traceback.
            raise AcquisitionError(
                "YouTube download failed; check that the URL is public and accessible"
            ) from None


def acquire_youtube_source(
    source: str, workspace: Path, *, time_range: TimeRange | None = None
) -> AcquiredSource:
    """Functional adapter entry point for callers that prefer a function."""
    return YoutubeAdapter().acquire(source, workspace, time_range=time_range)


YouTubeAdapter = YoutubeAdapter
