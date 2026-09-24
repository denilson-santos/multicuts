"""Cache identity and persistence for final clip publication."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isclose
from pathlib import Path

from multicuts.artifacts import WorkspacePaths
from multicuts.errors import ArtifactError, RenderingError
from multicuts.models import ClipTranscript, MediaInfo, RenderedClip

SUBTITLE_ARTIFACT_SCHEMA_VERSION = 1
SUBTITLE_RENDER_VERSION = "subtitle-render-v1"
_FINAL_DURATION_TOLERANCE_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class FinalClipPaths:
    """Controlled output paths for one final clip and its subtitle evidence."""

    video: Path
    metadata: Path
    cues_json: Path
    srt: Path
    ass: Path


def _clip_record(clip: ClipTranscript) -> object:
    """Normalize dataclass tuples to the JSON shape used in persisted metadata."""
    return json.loads(json.dumps(asdict(clip), ensure_ascii=False, allow_nan=False))


def _template_directory_identity(template_dir: Path | None) -> dict[str, str | None]:
    if template_dir is None:
        return {"path": None, "sha256": None}
    try:
        root = template_dir.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise OSError("template directory is not a directory")
        digest = sha256()
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise OSError("template directory contains a symbolic link")
            if path.is_file():
                relative = path.relative_to(root).as_posix().encode("utf-8")
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                contents = path.read_bytes()
                digest.update(len(contents).to_bytes(8, "big"))
                digest.update(contents)
    except OSError as exc:
        raise ArtifactError(
            "Could not fingerprint the subtitle template directory"
        ) from exc
    return {"path": str(root), "sha256": digest.hexdigest()}


def subtitle_cache_key(
    raw: RenderedClip,
    clip: ClipTranscript | None,
    *,
    subtitles_enabled: bool,
    template: str | None,
    template_dir: Path | None,
    provider_version: str | None,
) -> str:
    """Hash only raw, transcript, presentation, and provider inputs."""
    if not isinstance(subtitles_enabled, bool):
        raise ArtifactError("Subtitle enabled setting is invalid")
    if subtitles_enabled:
        if clip is None or not provider_version or not provider_version.strip():
            raise ArtifactError("Subtitle cache identity is incomplete")
        template_identity = _template_directory_identity(template_dir)
        transcript_identity = _clip_record(clip)
    else:
        template_identity = {"path": None, "sha256": None}
        transcript_identity = None
    identity = {
        "schema_version": SUBTITLE_ARTIFACT_SCHEMA_VERSION,
        "stage_version": SUBTITLE_RENDER_VERSION,
        "subtitles_enabled": subtitles_enabled,
        "raw_cache_key": raw.cache_key,
        "raw_renderer_version": raw.renderer_version,
        "geometry": [raw.width, raw.height],
        "duration": raw.duration,
        "has_audio": raw.has_audio,
        "clip_transcript": transcript_identity,
        "template_requested": template if subtitles_enabled else None,
        "template_directory": template_identity,
        "provider_version": provider_version if subtitles_enabled else None,
    }
    try:
        canonical = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ArtifactError("Subtitle cache identity is invalid") from exc
    return f"sha256-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


def final_clip_paths(
    paths: WorkspacePaths, raw: RenderedClip, cache_key: str
) -> FinalClipPaths:
    """Return deterministic final-output paths without exposing source names."""
    if not cache_key.startswith("sha256-v1:"):
        raise ArtifactError("Subtitle cache identity is invalid")
    digest = sha256(f"{raw.refined.candidate_id}\0{cache_key}".encode()).hexdigest()[
        :20
    ]
    stem = f"{raw.refined.rank:03d}-{digest}"
    clips_dir = paths.root / "clips"
    subtitle_dir = paths.rendering / "subtitles"
    try:
        root = paths.root.resolve(strict=True)
        if not clips_dir.resolve(strict=False).is_relative_to(root):
            raise ArtifactError("Final clip output escapes the run workspace")
        if not subtitle_dir.resolve(strict=False).is_relative_to(root):
            raise ArtifactError("Subtitle artifacts escape the run workspace")
    except (OSError, RuntimeError) as exc:
        raise ArtifactError("Could not validate final clip output paths") from exc
    return FinalClipPaths(
        video=clips_dir / f"{stem}.mp4",
        metadata=subtitle_dir / f"{stem}.json",
        cues_json=subtitle_dir / f"{stem}.cues.json",
        srt=subtitle_dir / f"{stem}.srt",
        ass=subtitle_dir / f"{stem}.ass",
    )


def _regular_nonempty(path: Path) -> bool:
    return not path.is_symlink() and path.is_file() and path.stat().st_size > 0


def read_final_clip(
    output: FinalClipPaths,
    raw: RenderedClip,
    clip: ClipTranscript | None,
    *,
    cache_key: str,
    subtitles_enabled: bool,
    template: str | None,
    template_dir: Path | None,
    provider_version: str | None,
    inspect: Callable[[Path], MediaInfo],
) -> Path | None:
    """Reuse a final clip only when metadata and probed media both match."""
    metadata_exists = os.path.lexists(output.metadata)
    video_exists = os.path.lexists(output.video)
    if not metadata_exists and not video_exists:
        return None
    if not metadata_exists or not video_exists:
        raise ArtifactError(
            "Final clip artifact is incomplete; remove its metadata and video to retry"
        )
    if output.metadata.is_symlink() or output.video.is_symlink():
        raise ArtifactError("Final clip artifact paths must be regular files")
    try:
        payload = json.loads(output.metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("Could not read final clip metadata") from exc
    expected_transcript = (
        _clip_record(clip) if subtitles_enabled and clip is not None else None
    )
    expected_template_dir = (
        _template_directory_identity(template_dir)
        if subtitles_enabled
        else {"path": None, "sha256": None}
    )
    expected = {
        "schema_version": SUBTITLE_ARTIFACT_SCHEMA_VERSION,
        "stage_version": SUBTITLE_RENDER_VERSION,
        "cache_key": cache_key,
        "subtitles_enabled": subtitles_enabled,
        "raw_cache_key": raw.cache_key,
        "candidate_id": raw.refined.candidate_id,
        "render_start": raw.refined.render_start,
        "render_end": raw.refined.render_end,
        "filename": output.video.name,
        "width": raw.width,
        "height": raw.height,
        "has_audio": raw.has_audio,
        "clip_transcript": expected_transcript,
        "template_requested": template if subtitles_enabled else None,
        "template_directory": expected_template_dir,
        "provider_version": provider_version if subtitles_enabled else None,
    }
    if not isinstance(payload, dict) or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        raise ArtifactError(
            "Final clip metadata does not match this render; "
            "remove its artifacts to retry"
        )
    duration = payload.get("duration")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or duration <= 0
    ):
        raise ArtifactError("Final clip metadata has an invalid duration")
    if subtitles_enabled:
        if not all(
            _regular_nonempty(path)
            for path in (output.cues_json, output.srt, output.ass)
        ):
            raise ArtifactError("Cached subtitle artifact set is incomplete")
        if payload.get("subtitle_artifacts") != {
            "cues_json": output.cues_json.name,
            "srt": output.srt.name,
            "ass": output.ass.name,
        }:
            raise ArtifactError("Final clip subtitle metadata is invalid")
    elif payload.get("subtitle_artifacts") is not None:
        raise ArtifactError(
            "Subtitle-disabled metadata unexpectedly includes subtitles"
        )
    if subtitles_enabled and (
        not isinstance(payload.get("template_resolved"), str)
        or not payload["template_resolved"].strip()
    ):
        raise ArtifactError("Final clip has no resolved subtitle template")
    try:
        media = inspect(output.video)
    except RenderingError as exc:
        raise ArtifactError("Could not validate cached final clip") from exc
    if (
        (media.presentation_width, media.presentation_height) != (raw.width, raw.height)
        or media.has_audio != raw.has_audio
        or not isclose(
            media.duration,
            raw.duration,
            rel_tol=0.0,
            abs_tol=_FINAL_DURATION_TOLERANCE_SECONDS,
        )
        or media.duration != float(duration)
    ):
        raise ArtifactError("Cached final clip media does not match its metadata")
    return output.video


def write_final_clip_metadata(
    paths: WorkspacePaths,
    output: FinalClipPaths,
    raw: RenderedClip,
    clip: ClipTranscript | None,
    *,
    cache_key: str,
    subtitles_enabled: bool,
    template: str | None,
    template_dir: Path | None,
    provider_version: str | None,
    template_resolved: str | None,
    duration: float,
) -> None:
    """Atomically publish provenance after all final artifacts are complete."""
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError("Completed output already exists; refusing to overwrite")
    payload: dict[str, object] = {
        "schema_version": SUBTITLE_ARTIFACT_SCHEMA_VERSION,
        "stage_version": SUBTITLE_RENDER_VERSION,
        "cache_key": cache_key,
        "subtitles_enabled": subtitles_enabled,
        "raw_cache_key": raw.cache_key,
        "candidate_id": raw.refined.candidate_id,
        "render_start": raw.refined.render_start,
        "render_end": raw.refined.render_end,
        "filename": output.video.name,
        "width": raw.width,
        "height": raw.height,
        "duration": duration,
        "has_audio": raw.has_audio,
        "clip_transcript": (
            _clip_record(clip) if subtitles_enabled and clip is not None else None
        ),
        "template_requested": template if subtitles_enabled else None,
        "template_resolved": template_resolved if subtitles_enabled else None,
        "template_directory": (
            _template_directory_identity(template_dir)
            if subtitles_enabled
            else {"path": None, "sha256": None}
        ),
        "provider_version": provider_version if subtitles_enabled else None,
        "subtitle_artifacts": (
            {
                "cues_json": output.cues_json.name,
                "srt": output.srt.name,
                "ass": output.ass.name,
            }
            if subtitles_enabled
            else None
        ),
    }
    temporary: Path | None = None
    try:
        output.metadata.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix="subtitle-",
            suffix=".tmp",
            dir=paths.work,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output.metadata)
    except FileExistsError as exc:
        raise ArtifactError("Final clip metadata already exists") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactError("Could not publish final clip metadata") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def publish_copy_without_overwrite(source: Path, target: Path) -> None:
    """Copy an auxiliary artifact atomically without replacing prior output."""
    try:
        if source.is_symlink() or not source.is_file() or source.stat().st_size <= 0:
            raise ArtifactError("Subtitle source artifact is missing or empty")
    except OSError as exc:
        raise ArtifactError("Could not inspect subtitle source artifact") from exc
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="subtitle-",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            with source.open("rb") as source_stream:
                while chunk := source_stream.read(1024 * 1024):
                    stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
    except FileExistsError as exc:
        raise ArtifactError("Subtitle artifact already exists") from exc
    except OSError as exc:
        raise ArtifactError("Could not persist subtitle artifact") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
