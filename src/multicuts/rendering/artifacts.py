"""Stage-specific identity and metadata for validated raw clip renders."""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import cast

from multicuts.artifacts import WorkspacePaths
from multicuts.errors import ArtifactError, MediaError, RenderingError
from multicuts.models import (
    MediaInfo,
    RefinedSelection,
    RenderedClip,
    RenderRequest,
)
from multicuts.rendering.cutter import RENDERER_VERSION, validate_rendered_media

RENDER_ARTIFACT_SCHEMA_VERSION = 1


class InvalidRenderArtifactError(ArtifactError):
    """A raw-render artifact exists but cannot be reused safely."""


def render_cache_key(
    refined: RefinedSelection,
    media: MediaInfo,
    *,
    source_fingerprint: str,
    aspect_ratio: str,
    target_width: int,
    target_height: int,
    renderer_version: str,
) -> str:
    """Hash only source, interval, geometry and renderer inputs for a raw clip."""
    if not source_fingerprint.strip() or not renderer_version.strip():
        raise ArtifactError("Render identity is incomplete")
    if refined.requires_rescore:
        raise ArtifactError("Content requiring rescoring cannot enter rendering")
    if aspect_ratio not in ("original", "9:16"):
        raise ArtifactError("Render aspect ratio is unsupported")
    if aspect_ratio == "9:16" and (
        type(target_width) is not int
        or type(target_height) is not int
        or target_width <= 0
        or target_height <= 0
        or target_width % 2
        or target_height % 2
        or target_width * 16 != target_height * 9
    ):
        raise ArtifactError("Render target geometry is invalid")
    identity = {
        "schema_version": RENDER_ARTIFACT_SCHEMA_VERSION,
        "render_algorithm_version": RENDERER_VERSION,
        "source_fingerprint": source_fingerprint,
        "source_media": asdict(media),
        "candidate_id": refined.candidate_id,
        "render_start": refined.render_start,
        "render_end": refined.render_end,
        "refinement_version": refined.version,
        "aspect_ratio": aspect_ratio,
        "target_width": target_width if aspect_ratio == "9:16" else None,
        "target_height": target_height if aspect_ratio == "9:16" else None,
        "renderer_version": renderer_version,
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"sha256-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


def render_paths(
    paths: WorkspacePaths, refined: RefinedSelection, cache_key: str
) -> tuple[Path, Path]:
    """Return deterministic controlled raw-video and metadata paths."""
    if not cache_key.startswith("sha256-v1:"):
        raise ArtifactError("Render cache identity is invalid")
    digest = sha256(f"{refined.candidate_id}\0{cache_key}".encode()).hexdigest()[:24]
    stem = digest
    return paths.raw_clips / f"{stem}.mp4", paths.rendering / f"{stem}.json"


def _record(request: RenderRequest, result: RenderedClip) -> dict[str, object]:
    return {
        "schema_version": RENDER_ARTIFACT_SCHEMA_VERSION,
        "render_algorithm_version": RENDERER_VERSION,
        "cache_key": request.cache_key,
        "candidate_id": request.refined.candidate_id,
        "render_start": request.refined.render_start,
        "render_end": request.refined.render_end,
        "filename": result.path.name,
        "width": result.width,
        "height": result.height,
        "duration": result.duration,
        "has_audio": result.has_audio,
        "renderer_version": result.renderer_version,
    }


def _decode(value: object, request: RenderRequest) -> tuple[int, int, float, bool]:
    if not isinstance(value, dict):
        raise InvalidRenderArtifactError("Render metadata is not an object")
    payload = cast(dict[str, object], value)
    expected_keys = {
        "schema_version",
        "render_algorithm_version",
        "cache_key",
        "candidate_id",
        "render_start",
        "render_end",
        "filename",
        "width",
        "height",
        "duration",
        "has_audio",
        "renderer_version",
    }
    if set(payload) != expected_keys:
        raise InvalidRenderArtifactError("Render metadata has invalid fields")
    if (
        payload["schema_version"] != RENDER_ARTIFACT_SCHEMA_VERSION
        or payload["render_algorithm_version"] != RENDERER_VERSION
        or payload["cache_key"] != request.cache_key
        or payload["candidate_id"] != request.refined.candidate_id
        or payload["render_start"] != request.refined.render_start
        or payload["render_end"] != request.refined.render_end
        or payload["filename"] != request.output_path.name
        or payload["renderer_version"] != request.renderer_version
    ):
        raise InvalidRenderArtifactError("Render metadata provenance is invalid")
    width = payload["width"]
    height = payload["height"]
    duration = payload["duration"]
    has_audio = payload["has_audio"]
    if (
        type(width) is not int
        or type(height) is not int
        or width <= 0
        or height <= 0
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not isfinite(duration)
        or duration <= 0
        or type(has_audio) is not bool
    ):
        raise InvalidRenderArtifactError("Render metadata geometry is invalid")
    return width, height, float(duration), has_audio


def read_render(
    request: RenderRequest,
    metadata_path: Path,
    *,
    inspect: Callable[[Path], MediaInfo],
) -> RenderedClip | None:
    """Reuse a matching raw clip only after probing the actual media file."""
    if metadata_path.is_symlink() or request.output_path.is_symlink():
        raise ArtifactError("Render paths must be regular files")
    try:
        with metadata_path.open(encoding="utf-8") as artifact_file:
            payload: object = json.load(artifact_file)
    except FileNotFoundError:
        return None
    except (UnicodeError, ValueError) as exc:
        raise InvalidRenderArtifactError("Render metadata is not valid JSON") from exc
    except OSError as exc:
        raise ArtifactError("Could not read render metadata") from exc
    width, height, duration, has_audio = _decode(payload, request)
    if not request.output_path.is_file():
        raise InvalidRenderArtifactError("Render media is missing")
    try:
        actual = inspect(request.output_path)
        validate_rendered_media(request, actual)
    except (MediaError, RenderingError) as exc:
        raise InvalidRenderArtifactError("Render media failed validation") from exc
    if (
        (actual.presentation_width, actual.presentation_height) != (width, height)
        or actual.duration != duration
        or actual.has_audio != has_audio
    ):
        raise InvalidRenderArtifactError("Render media differs from metadata")
    return RenderedClip(
        refined=request.refined,
        path=request.output_path,
        width=width,
        height=height,
        duration=duration,
        has_audio=has_audio,
        renderer_version=request.renderer_version,
        cache_key=request.cache_key,
    )


def write_render(
    paths: WorkspacePaths,
    request: RenderRequest,
    result: RenderedClip,
    metadata_path: Path,
) -> None:
    """Atomically record a newly published, validated raw clip."""
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError("Completed output already exists; refusing to overwrite")
    if metadata_path.is_symlink() or request.output_path.is_symlink():
        raise ArtifactError("Render paths must be regular files")
    if (
        result.refined != request.refined
        or result.path != request.output_path
        or result.renderer_version != request.renderer_version
        or result.cache_key != request.cache_key
        or not result.path.is_file()
    ):
        raise ArtifactError("Rendered clip does not match its request")
    payload = _record(request, result)
    _decode(payload, request)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix="render-",
            suffix=".tmp",
            dir=paths.work,
            delete=False,
        ) as artifact_file:
            temporary = Path(artifact_file.name)
            json.dump(
                payload,
                artifact_file,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            artifact_file.write("\n")
            artifact_file.flush()
            os.fsync(artifact_file.fileno())
        os.replace(temporary, metadata_path)
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactError("Could not publish render metadata") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
