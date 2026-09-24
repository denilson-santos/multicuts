"""Transcription and subtitles through supported multisubs boundaries."""

import importlib
import importlib.metadata
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import NoReturn, cast

from multicuts.adapters.multisubs_subtitles import SubtitleArtifacts, render_subtitles
from multicuts.errors import TranscriptionError
from multicuts.models import ClipTranscript, Transcript, TranscriptSegment, Word


@dataclass(frozen=True, slots=True)
class TranscriptionArtifact:
    """Validated provider JSON location and source-transcription provenance."""

    json_path: Path
    provider_version: str
    language_requested: str | None


def _invalid_field(field: str) -> NoReturn:
    raise TranscriptionError(f"multisubs JSON transcript has invalid {field}")


def _record(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _invalid_field(field)
    return cast(dict[str, object], value)


def _items(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        _invalid_field(field)
    return cast(list[object], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid_field(field)
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid_field(field)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise TranscriptionError(
            f"multisubs JSON transcript has invalid {field}"
        ) from exc
    if not isfinite(number):
        _invalid_field(field)
    return number


def _interval(
    record: dict[str, object], field: str
) -> tuple[float | None, float | None]:
    start = record.get("start")
    end = record.get("end")
    if start is None and end is None:
        return None, None
    if start is None or end is None:
        _invalid_field(f"{field} timing")
    return _number(start, f"{field} start"), _number(end, f"{field} end")


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def _normalize_artifact(artifact: TranscriptionArtifact) -> Transcript:
    try:
        with artifact.json_path.open(encoding="utf-8") as artifact_file:
            payload: object = json.load(
                artifact_file, parse_constant=_reject_json_constant
            )
    except (OSError, UnicodeError, ValueError) as exc:
        raise TranscriptionError(
            "multisubs did not produce a readable JSON transcript"
        ) from exc

    root = _record(payload, "root object")
    if root.get("schema_version") != 3 or isinstance(root.get("schema_version"), bool):
        _invalid_field("schema version")
    metadata = _record(root.get("metadata"), "metadata")
    if metadata.get("task") != "transcribe":
        _invalid_field("task")
    detected_language = _text(metadata.get("language"), "detected language")
    duration = _number(metadata.get("duration"), "duration")
    if duration <= 0:
        _invalid_field("duration")
    transcription = _record(root.get("transcription"), "transcription")
    full_text = _text(transcription.get("text"), "transcription text")
    raw_segments = _items(transcription.get("segments"), "segments")
    if not raw_segments:
        _invalid_field("segments")

    segments: list[TranscriptSegment] = []
    words: list[Word] = []
    for index, raw_segment in enumerate(raw_segments):
        field = f"segment {index}"
        segment = _record(raw_segment, field)
        start, end = _interval(segment, field)
        try:
            segments.append(
                TranscriptSegment(
                    _text(segment.get("text"), f"{field} text"), start, end
                )
            )
        except ValueError as exc:
            raise TranscriptionError(
                f"multisubs JSON transcript has invalid {field}"
            ) from exc
        for word_index, raw_word in enumerate(
            _items(segment.get("words", []), f"{field} words")
        ):
            word_field = f"{field} word {word_index}"
            word = _record(raw_word, word_field)
            word_start, word_end = _interval(word, word_field)
            raw_score = word.get("score")
            confidence = (
                None if raw_score is None else _number(raw_score, f"{word_field} score")
            )
            try:
                words.append(
                    Word(
                        _text(word.get("word"), f"{word_field} text"),
                        word_start,
                        word_end,
                        confidence,
                    )
                )
            except ValueError as exc:
                raise TranscriptionError(
                    f"multisubs JSON transcript has invalid {word_field}"
                ) from exc

    try:
        return Transcript(
            language_requested=artifact.language_requested,
            language_detected=detected_language,
            duration=duration,
            text=full_text,
            segments=tuple(segments),
            words=tuple(words),
            provider="multisubs",
            provider_version=artifact.provider_version,
        )
    except ValueError as exc:
        raise TranscriptionError("multisubs JSON transcript is invalid") from exc


class MultisubsAdapter:
    """Normalize source transcription and render source-derived clip subtitles."""

    def subtitle_clip(
        self,
        video_path: Path,
        clip: ClipTranscript,
        *,
        template: str | None,
        template_dir: Path | None,
        workspace: Path,
    ) -> SubtitleArtifacts:
        """Render existing clip words without starting a new ASR pass."""
        return render_subtitles(
            video_path,
            clip,
            template=template,
            template_dir=template_dir,
            workspace=workspace,
        )

    def version(self) -> str:
        """Read installed provider metadata without loading a transcription model."""
        try:
            return importlib.metadata.version("multisubs")
        except importlib.metadata.PackageNotFoundError as exc:
            raise TranscriptionError(
                "multisubs is unavailable; check the multisubs installation"
            ) from exc

    def transcribe(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
    ) -> Transcript:
        """Return a project-owned transcript from one public provider call."""
        artifact = self.transcribe_to_artifact(
            video_path, language=language, model=model, workspace=workspace
        )
        return _normalize_artifact(artifact)

    def transcribe_to_artifact(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
    ) -> TranscriptionArtifact:
        """Generate source artifacts inside the workspace and verify the JSON."""
        try:
            provider = importlib.import_module("multisubs")
            generate = provider.generate_transcriptions
            version = provider.__version__
        except Exception as exc:
            raise TranscriptionError(
                "multisubs public transcription API is unavailable; "
                "check the multisubs installation"
            ) from exc
        if not callable(generate) or not isinstance(version, str) or not version:
            raise TranscriptionError("multisubs public transcription API is invalid")

        workspace_root = workspace.expanduser().resolve(strict=False)
        output_dir = workspace_root / "multisubs"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            actual_output_dir = output_dir.resolve(strict=True)
        except OSError as exc:
            raise TranscriptionError(
                "Could not prepare the multisubs workspace; check its permissions"
            ) from exc
        if not actual_output_dir.is_relative_to(workspace_root):
            raise TranscriptionError(
                "multisubs workspace must stay inside the configured workspace"
            )

        model_options = {} if model == "default" else {"model_name": model}
        try:
            generated = generate(
                video_path,
                actual_output_dir,
                lang=language,
                task="transcribe",
                **model_options,
            )
        except Exception as exc:
            raise TranscriptionError(
                "multisubs could not transcribe the source; check its audio, "
                "language, and model compatibility"
            ) from exc

        if (
            not isinstance(generated, tuple)
            or len(generated) != 3
            or any(not isinstance(path, (str, Path)) for path in generated)
        ):
            raise TranscriptionError("multisubs returned invalid artifact paths")

        try:
            artifact_paths = tuple(
                Path(path).resolve(strict=True) for path in generated
            )
            if any(
                not path.is_relative_to(actual_output_dir) or not path.is_file()
                for path in artifact_paths
            ):
                raise TranscriptionError(
                    "multisubs artifacts must be files inside its workspace"
                )
            resolved_json = artifact_paths[0]
            with resolved_json.open(encoding="utf-8") as artifact_file:
                payload = json.load(artifact_file)
        except (OSError, UnicodeError, ValueError) as exc:
            raise TranscriptionError(
                "multisubs did not produce a readable JSON transcript"
            ) from exc
        if not isinstance(payload, dict) or not payload:
            raise TranscriptionError(
                "multisubs produced an empty or invalid JSON transcript"
            )

        return TranscriptionArtifact(
            json_path=resolved_json,
            provider_version=version,
            language_requested=language,
        )
