"""Provider-independent source routing and acquisition workspace handling."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

from multicuts.errors import AcquisitionError
from multicuts.local_source import acquire_local_source
from multicuts.models import AcquiredSource

_SUPPORTED_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
    }
)
_YOUTUBE_SCHEMES = frozenset({"http", "https"})
_MAX_VIDEO_ID_LENGTH = 128


class SourceProvider(Protocol):
    """The narrow boundary implemented by remote source providers."""

    def acquire(self, source: str, workspace: Path) -> AcquiredSource:
        """Acquire one source into the caller-controlled workspace."""
        ...


@dataclass(frozen=True, slots=True)
class YouTubeReference:
    """Validated identity extracted from a supported YouTube URL."""

    video_id: str
    scheme: str
    host: str
    path: str

    @property
    def canonical_url(self) -> str:
        """Return a credential-free canonical URL for metadata and identity."""
        if self.host == "youtu.be":
            return f"{self.scheme}://youtu.be/{self.video_id}"
        return f"{self.scheme}://{self.host}/watch?v={self.video_id}"


def _valid_video_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > _MAX_VIDEO_ID_LENGTH:
        return None
    if any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in value
    ):
        return None
    return value


def parse_youtube_url(source: str) -> YouTubeReference | None:
    """Parse a supported YouTube URL without performing network access."""
    if not isinstance(source, str) or not source.strip():
        return None
    try:
        parsed = urlsplit(source.strip())
    except ValueError:
        return None
    if parsed.scheme.casefold() not in _YOUTUBE_SCHEMES or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port not in (None, 80, 443):
        return None
    host = parsed.hostname
    if host is None:
        return None
    host = host.rstrip(".").casefold()
    if host not in _SUPPORTED_YOUTUBE_HOSTS:
        return None

    video_id: str | None = None
    path = parsed.path.rstrip("/")
    if host == "youtu.be":
        if path.count("/") != 1:
            return None
        video_id = _valid_video_id(path.removeprefix("/"))
    elif path == "/watch":
        query = parse_qs(parsed.query, keep_blank_values=True)
        values = query.get("v")
        if values and len(values) == 1:
            video_id = _valid_video_id(values[0])
    else:
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if path.startswith(prefix):
                suffix = path.removeprefix(prefix)
                if "/" not in suffix:
                    video_id = _valid_video_id(suffix)
                break
    if video_id is None:
        return None
    return YouTubeReference(
        video_id=video_id,
        scheme=parsed.scheme.casefold(),
        host=host,
        path=path,
    )


def is_supported_youtube_url(source: str) -> bool:
    """Return whether ``source`` is a supported YouTube URL."""
    return parse_youtube_url(source) is not None


def prepare_acquisition_workspace(output_dir: Path) -> Path:
    """Create the explicit, project-controlled workspace for acquisition."""
    if not isinstance(output_dir, Path):
        raise AcquisitionError("Acquisition workspace root must be a Path")
    try:
        root = output_dir.expanduser().resolve(strict=False)
        workspace = root / ".work" / "acquisition"
        workspace.mkdir(parents=True, exist_ok=True)
        resolved_workspace = workspace.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AcquisitionError("Could not prepare the acquisition workspace") from exc
    if not resolved_workspace.is_dir() or not resolved_workspace.is_relative_to(root):
        raise AcquisitionError("Acquisition workspace escapes the output directory")
    return resolved_workspace


def acquire_source(
    source: str | Path,
    workspace: Path,
    *,
    youtube_provider: SourceProvider | None = None,
) -> AcquiredSource:
    """Route one source to local acquisition or the YouTube adapter."""
    if not isinstance(workspace, Path):
        raise AcquisitionError("Acquisition workspace must be a Path")
    if isinstance(source, Path):
        return acquire_local_source(source, workspace)
    if not isinstance(source, str):
        raise AcquisitionError("Source must be a path or URL string")
    reference = parse_youtube_url(source)
    if reference is not None:
        from multicuts.adapters.youtube import YoutubeAdapter

        provider = (
            youtube_provider if youtube_provider is not None else YoutubeAdapter()
        )
        return provider.acquire(source, workspace)

    try:
        parsed = urlsplit(source)
    except (TypeError, ValueError) as exc:
        raise AcquisitionError(
            "Source is neither a valid local path nor YouTube URL"
        ) from exc
    if parsed.scheme and parsed.netloc:
        raise AcquisitionError(
            "Unsupported source URL; provide a supported YouTube URL"
        )
    if parsed.scheme.casefold() in _YOUTUBE_SCHEMES:
        raise AcquisitionError(
            "Unsupported source URL; provide a supported YouTube URL"
        )
    return acquire_local_source(source, workspace)
