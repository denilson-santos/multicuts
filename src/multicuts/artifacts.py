"""Output-local paths and safe JSON persistence for transcription artifacts."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import NoReturn, cast

from multicuts.errors import ArtifactError
from multicuts.models import AcquiredSource, Transcript, TranscriptSegment, Word

TRANSCRIPT_SCHEMA_VERSION = 1
TRANSCRIPTION_STAGE_VERSION = 1
TRANSCRIPTION_TASK = "transcribe"


class InvalidTranscriptArtifactError(ArtifactError):
    """A cache artifact exists but cannot be reused safely."""


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Controlled locations for one source and transcription configuration."""

    root: Path
    manifest: Path
    source_metadata: Path
    transcript: Path
    work: Path


def transcription_cache_key(
    *,
    source_fingerprint: str,
    provider: str,
    provider_version: str,
    model: str,
    language: str | None,
) -> str:
    """Hash only inputs that can change source transcription."""
    if any(
        not value.strip()
        for value in (source_fingerprint, provider, provider_version, model)
    ):
        raise ArtifactError("Transcription cache identity is incomplete")
    if language is not None and not language.strip():
        raise ArtifactError("Transcription cache language is invalid")
    identity = {
        "source_fingerprint": source_fingerprint,
        "provider": provider,
        "provider_version": provider_version,
        "model": model,
        "language_requested": language,
        "task": TRANSCRIPTION_TASK,
        "stage_version": TRANSCRIPTION_STAGE_VERSION,
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
    }
    canonical = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


def prepare_workspace(
    output_root: Path, source: AcquiredSource, *, cache_key: str
) -> WorkspacePaths:
    """Create an output-local workspace without using untrusted path components."""
    if not cache_key.startswith("sha256-v1:"):
        raise ArtifactError("Transcription cache identity is invalid")
    identity = sha256(f"{source.fingerprint}\0{cache_key}".encode()).hexdigest()
    try:
        base = output_root.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ArtifactError("Could not resolve the output workspace") from exc
    root = base / f"source-{identity}"
    paths = WorkspacePaths(
        root=root,
        manifest=root / "manifest.json",
        source_metadata=root / "source" / "metadata.json",
        transcript=root / "transcript" / "transcript.json",
        work=root / ".work",
    )
    try:
        base.mkdir(parents=True, exist_ok=True)
        for directory in (
            root,
            paths.source_metadata.parent,
            paths.transcript.parent,
            paths.work,
        ):
            directory.mkdir(exist_ok=True)
            if not directory.resolve(strict=True).is_relative_to(base):
                raise ArtifactError("Workspace path escapes the output directory")
    except OSError as exc:
        raise ArtifactError("Could not prepare the output workspace") from exc
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError(
            "Completed output already exists; choose another output directory"
        )
    return paths


def _invalid(field: str) -> NoReturn:
    raise InvalidTranscriptArtifactError(f"Transcript artifact has invalid {field}")


def _object(value: object, field: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid(field)
    return cast(dict[str, object], value)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, (list, tuple)):
        _invalid(field)
    return list(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(field)
    return value


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(field)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise InvalidTranscriptArtifactError(
            f"Transcript artifact has invalid {field}"
        ) from exc
    if not isfinite(number):
        _invalid(field)
    return number


def _optional_number(value: object, field: str) -> float | None:
    return None if value is None else _number(value, field)


def _decode_transcript(value: object) -> Transcript:
    record = _object(
        value,
        "transcript",
        {
            "language_requested",
            "language_detected",
            "duration",
            "text",
            "segments",
            "words",
            "provider",
            "provider_version",
        },
    )
    segments: list[TranscriptSegment] = []
    raw_segments = _list(record["segments"], "segments")
    if not raw_segments:
        _invalid("segments")
    for index, item in enumerate(raw_segments):
        field = f"segment {index}"
        segment = _object(item, field, {"text", "start", "end"})
        try:
            segments.append(
                TranscriptSegment(
                    _string(segment["text"], f"{field} text"),
                    _optional_number(segment["start"], f"{field} start"),
                    _optional_number(segment["end"], f"{field} end"),
                )
            )
        except ValueError as exc:
            raise InvalidTranscriptArtifactError(
                f"Transcript artifact has invalid {field}"
            ) from exc
    words: list[Word] = []
    for index, item in enumerate(_list(record["words"], "words")):
        field = f"word {index}"
        word = _object(item, field, {"text", "start", "end", "confidence"})
        try:
            words.append(
                Word(
                    _string(word["text"], f"{field} text"),
                    _optional_number(word["start"], f"{field} start"),
                    _optional_number(word["end"], f"{field} end"),
                    _optional_number(word["confidence"], f"{field} confidence"),
                )
            )
        except ValueError as exc:
            raise InvalidTranscriptArtifactError(
                f"Transcript artifact has invalid {field}"
            ) from exc
    try:
        return Transcript(
            language_requested=_optional_string(
                record["language_requested"], "requested language"
            ),
            language_detected=_optional_string(
                record["language_detected"], "detected language"
            ),
            duration=_number(record["duration"], "duration"),
            text=_string(record["text"], "text"),
            segments=tuple(segments),
            words=tuple(words),
            provider=_string(record["provider"], "provider"),
            provider_version=_string(record["provider_version"], "provider version"),
        )
    except ValueError as exc:
        raise InvalidTranscriptArtifactError(
            "Transcript artifact has invalid model values"
        ) from exc


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def read_transcript(paths: WorkspacePaths, *, cache_key: str) -> Transcript | None:
    """Return a validated matching transcript or a miss for absent/stale data."""
    if paths.transcript.is_symlink():
        raise ArtifactError("Transcript artifact must be a regular file")
    try:
        with paths.transcript.open(encoding="utf-8") as artifact_file:
            payload: object = json.load(
                artifact_file, parse_constant=_reject_json_constant
            )
    except FileNotFoundError:
        return None
    except (UnicodeError, ValueError) as exc:
        raise InvalidTranscriptArtifactError(
            "Transcript artifact is not valid JSON"
        ) from exc
    except OSError as exc:
        raise ArtifactError("Could not read the transcript artifact") from exc
    root = _object(
        payload,
        "root object",
        {"schema_version", "stage_version", "task", "cache_key", "transcript"},
    )
    if (
        type(root["schema_version"]) is not int
        or root["schema_version"] != TRANSCRIPT_SCHEMA_VERSION
        or type(root["stage_version"]) is not int
        or root["stage_version"] != TRANSCRIPTION_STAGE_VERSION
        or root["task"] != TRANSCRIPTION_TASK
    ):
        _invalid("schema or stage version")
    if not isinstance(root["cache_key"], str):
        _invalid("cache key")
    if root["cache_key"] != cache_key:
        return None
    return _decode_transcript(root["transcript"])


def write_transcript(
    paths: WorkspacePaths, transcript: Transcript, *, cache_key: str, replace: bool
) -> None:
    """Publish a complete transcript from a temporary file on the same volume."""
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError("Completed output already exists; refusing to overwrite")
    if paths.transcript.is_symlink():
        raise ArtifactError("Transcript artifact must be a regular file")
    if paths.transcript.exists() and not replace:
        raise ArtifactError("Transcript artifact already exists; refusing to overwrite")
    transcript_payload = asdict(transcript)
    try:
        _decode_transcript(transcript_payload)
    except InvalidTranscriptArtifactError as exc:
        raise ArtifactError("Cannot publish an invalid normalized transcript") from exc
    payload = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "stage_version": TRANSCRIPTION_STAGE_VERSION,
        "task": TRANSCRIPTION_TASK,
        "cache_key": cache_key,
        "transcript": transcript_payload,
    }
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix="transcript-",
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
        os.replace(temporary, paths.transcript)
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactError("Could not publish the transcript artifact") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
