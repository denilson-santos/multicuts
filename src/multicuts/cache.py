"""Validated transcript and AI response caches, separate from runs."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from math import isfinite
from pathlib import Path

from multicuts.clips import PROMPT_VERSION, SCORE_VERSION
from multicuts.errors import ArtifactError, ScoringError
from multicuts.models import AcquiredSource, Transcript, TranscriptSegment, Word


def _digest(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def transcript_content_fingerprint(transcript: Transcript) -> str:
    """Fingerprint normalized content, including observed timing and confidence."""
    return "sha256-v1:" + _digest(asdict(_decode_transcript(asdict(transcript))))


def transcript_paths(
    output_dir: Path,
    source: AcquiredSource,
    *,
    provider_version: str,
    model: str,
    language: str | None,
) -> tuple[Path, str]:
    if not provider_version.strip() or not model.strip():
        raise ArtifactError("Transcription cache identity is incomplete")
    key = "sha256-v1:" + _digest(
        {
            "source_fingerprint": source.fingerprint,
            "provider": "multisubs",
            "provider_version": provider_version,
            "model": model,
            "language_requested": language,
            "task": "transcribe",
            "stage_version": 1,
            "schema_version": 1,
        }
    )
    path = (
        output_dir.expanduser().resolve(strict=False)
        / ".cache"
        / "transcripts"
        / f"{key.removeprefix('sha256-v1:')}.json"
    )
    return path, key


def _number(value: object, *, optional: bool = False) -> float | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid number")
    result = float(value)
    if not isfinite(result):
        raise ValueError("nonfinite number")
    return result


def _string(value: object, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid string")
    return value


def _required_number(value: object) -> float:
    result = _number(value)
    if result is None:
        raise ValueError("missing number")
    return result


def _required_string(value: object) -> str:
    result = _string(value)
    if result is None:
        raise ValueError("missing string")
    return result


def _record(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("invalid transcript record")
    return value


def _decode_transcript(value: object) -> Transcript:
    record = _record(
        value,
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
    raw_segments, raw_words = record["segments"], record["words"]
    if (
        not isinstance(raw_segments, (list, tuple))
        or not raw_segments
        or not isinstance(raw_words, (list, tuple))
    ):
        raise ValueError("invalid transcript sequences")
    segments = []
    for item in raw_segments:
        entry = _record(item, {"text", "start", "end"})
        segments.append(
            TranscriptSegment(
                _required_string(entry["text"]),
                _number(entry["start"], optional=True),
                _number(entry["end"], optional=True),
            )
        )
    words = []
    for item in raw_words:
        entry = _record(item, {"text", "start", "end", "confidence"})
        words.append(
            Word(
                _required_string(entry["text"]),
                _number(entry["start"], optional=True),
                _number(entry["end"], optional=True),
                _number(entry["confidence"], optional=True),
            )
        )
    return Transcript(
        _string(record["language_requested"], optional=True),
        _string(record["language_detected"], optional=True),
        _required_number(record["duration"]),
        _required_string(record["text"]),
        tuple(segments),
        tuple(words),
        _required_string(record["provider"]),
        _required_string(record["provider_version"]),
    )


def load_transcript(path: Path, key: str) -> Transcript | None:
    if path.is_symlink():
        raise ArtifactError("Transcript cache path must be a regular file")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except FileNotFoundError:
        return None
    except (ValueError, UnicodeError):
        return None
    except OSError as exc:
        raise ArtifactError("Could not read transcript cache") from exc
    try:
        record = _record(payload, {"schema_version", "key", "transcript"})
        if (
            type(record["schema_version"]) is not int
            or record["schema_version"] != 1
            or record["key"] != key
        ):
            return None
        return _decode_transcript(record["transcript"])
    except (ValueError, TypeError, OverflowError):
        return None


def save_transcript(path: Path, transcript: Transcript, key: str) -> None:
    temporary: Path | None = None
    try:
        if path.is_symlink():
            raise ArtifactError("Transcript cache path must be a regular file")
        payload = {"schema_version": 1, "key": key, "transcript": asdict(transcript)}
        _decode_transcript(payload["transcript"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix="transcript-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError) as exc:
        raise ArtifactError("Could not publish transcript cache") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ai_cache_key(
    *,
    source_fingerprint: str,
    transcript_fingerprint: str,
    backend: str,
    model: str,
    task: str,
    prompt: str,
    schema: dict[str, object],
    effort: str | None = None,
) -> str:
    identity: dict[str, object] = {
        "prompt_version": PROMPT_VERSION,
        "score_version": SCORE_VERSION,
        "source": source_fingerprint,
        "transcript": transcript_fingerprint,
        "backend": backend,
        "model": model,
        "task": task,
        "prompt": prompt,
        "schema": schema,
    }
    if effort is not None:
        identity["effort"] = effort
    return _digest(identity)


def load_ai_response(
    output_dir: Path, key: str, *, validate: Callable[[object], object]
) -> object | None:
    path = (
        output_dir.expanduser().resolve(strict=False) / ".cache" / "ai" / f"{key}.json"
    )
    if path.is_symlink():
        raise ArtifactError("AI cache path must be a regular file")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except FileNotFoundError:
        return None
    except (UnicodeError, ValueError):
        return None
    except OSError as exc:
        raise ArtifactError("Could not read AI cache") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("key") != key
    ):
        return None
    try:
        validate(payload.get("response"))
    except (ValueError, ScoringError):
        return None
    return payload.get("response")


def save_ai_response(output_dir: Path, key: str, response: object) -> None:
    cache_dir = output_dir.expanduser().resolve(strict=False) / ".cache" / "ai"
    temporary: Path | None = None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{key}.json"
        if target.is_symlink():
            raise ArtifactError("AI cache path must be a regular file")
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=cache_dir,
            prefix="ai-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(
                {"schema_version": 1, "key": key, "response": response},
                stream,
                ensure_ascii=False,
                allow_nan=False,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except (OSError, ValueError) as exc:
        raise ArtifactError("Could not publish AI cache") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
