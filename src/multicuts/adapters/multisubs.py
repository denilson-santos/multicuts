"""Transcription and subtitles through supported multisubs boundaries."""

import importlib
import importlib.metadata
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import NoReturn, cast

from multicuts.errors import RenderingError, TranscriptionError
from multicuts.models import (
    ClipTranscript,
    ClipTranscriptWord,
    SubtitleArtifacts,
    Transcript,
    TranscriptSegment,
    Word,
)


@dataclass(frozen=True, slots=True)
class _TranscriptionArtifact:
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


def _normalize_artifact(artifact: _TranscriptionArtifact) -> Transcript:
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


def _require_provider_version() -> str:
    try:
        version = importlib.metadata.version("multisubs")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RenderingError(
            "multisubs is unavailable; install the configured multisubs 4.4 release"
        ) from exc
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except (ValueError, TypeError) as exc:
        raise RenderingError(f"Unsupported multisubs version: {version}") from exc
    if major != 4 or minor < 4:
        raise RenderingError(
            f"multisubs {version} cannot split timed cues to fit the clip; "
            "install version 4.4 or newer"
        )
    return version


def _source_text_for_words(segment_text: str, words: list[ClipTranscriptWord]) -> str:
    """Retain observed spacing when the selected words map to the source text."""
    tokens = [word.text.strip() for word in words]
    first = tokens[0]
    offset = segment_text.find(first)
    while offset >= 0:
        cursor = offset
        for token in tokens:
            while cursor < len(segment_text) and segment_text[cursor].isspace():
                cursor += 1
            if not segment_text.startswith(token, cursor):
                break
            cursor += len(token)
        else:
            return segment_text[offset:cursor]
        offset = segment_text.find(first, offset + 1)
    return " ".join(tokens)


def _timed_cues(clip: ClipTranscript) -> dict[str, object]:
    if not clip.word_animation_safe:
        raise RenderingError(
            "Clip subtitles require complete observed word timing; "
            "multisubs cannot infer missing word times"
        )
    language = clip.language_detected or clip.language_requested
    if (
        language is None
        or len(language) > 35
        or re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language) is None
    ):
        raise RenderingError("Clip subtitle language is unavailable or invalid")

    assigned: set[int] = set()
    cues: list[dict[str, object]] = []
    for segment in clip.segments:
        words = [
            word
            for word in clip.words
            if word.source_segment_index == segment.source_index
        ]
        if not words or segment.start is None or segment.end is None:
            raise RenderingError(
                f"Clip segment {segment.source_index} has no timed words or interval"
            )
        previous_end = -1.0
        for word in words:
            if word.start is None or word.end is None or word.start < previous_end:
                raise RenderingError(
                    f"Clip segment {segment.source_index} has overlapping word times"
                )
            previous_end = word.end
            assigned.add(word.source_index)
        first_start = words[0].start
        last_end = words[-1].end
        if first_start is None or last_end is None:
            raise RenderingError("Clip subtitle word timing is incomplete")
        cues.append(
            {
                "start": min(segment.start, first_start),
                "end": max(segment.end, last_end),
                "text": _source_text_for_words(segment.text, words),
                "words": [
                    {"start": word.start, "end": word.end, "text": word.text.strip()}
                    for word in words
                ],
            }
        )
    if not cues or len(assigned) != len(clip.words):
        raise RenderingError(
            "Clip words cannot be mapped to timed source segments for subtitles"
        )
    return {"schema_version": 1, "language": language, "cues": cues}


def _render_subtitles(
    video_path: Path,
    clip: ClipTranscript,
    *,
    template: str | None,
    template_dir: Path | None,
    workspace: Path,
) -> SubtitleArtifacts:
    """Use the public timed-cue CLI to generate SRT, ASS, and a subtitled video."""
    version = _require_provider_version()
    if not isinstance(clip, ClipTranscript):
        raise RenderingError("Clip subtitles require a ClipTranscript")
    try:
        video = video_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise RenderingError("Raw clip video is unavailable for subtitles") from exc
    if not video.is_file():
        raise RenderingError("Raw clip video is unavailable for subtitles")
    cues = _timed_cues(clip)

    workspace_root = workspace.expanduser().resolve(strict=False)
    output_dir = workspace_root / "rendered"
    cues_path = workspace_root / "cues.json"
    try:
        workspace_root.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(exist_ok=False)
        with cues_path.open("x", encoding="utf-8") as stream:
            json.dump(cues, stream, ensure_ascii=False, allow_nan=False)
    except (OSError, ValueError) as exc:
        raise RenderingError(
            "Could not prepare a fresh workspace for clip subtitles"
        ) from exc

    executable = Path(sys.executable).with_name("multisubs")
    if not executable.is_file():
        raise RenderingError(
            "multisubs CLI is unavailable beside the active Python interpreter"
        )
    command = [
        str(executable),
        "-i",
        str(video),
        "--cues-json",
        str(cues_path),
        "-o",
        str(output_dir),
    ]
    if template is not None:
        command.extend(("--template", template))
    if template_dir is not None:
        command.extend(("--template-dir", str(template_dir)))
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise RenderingError("Could not start the multisubs subtitle renderer") from exc
    if completed.returncode != 0:
        if (
            completed.stderr
            and "exceeds the subtitle layout envelope" in completed.stderr
        ):
            raise RenderingError(
                "multisubs subtitle text does not fit the selected template; "
                "try a template with more space or a smaller font"
            )
        raise RenderingError(
            "multisubs could not render this clip; check the selected template, "
            "word timing, video, fonts, and FFmpeg availability"
        )

    try:
        files = [path.resolve(strict=True) for path in output_dir.iterdir()]
        if (
            len(files) != 3
            or any(not path.is_file() or path.stat().st_size == 0 for path in files)
            or any(not path.is_relative_to(output_dir) for path in files)
        ):
            raise ValueError("unexpected subtitle artifacts")
        srt_path = next(path for path in files if path.suffix == ".srt")
        ass_path = next(path for path in files if path.suffix == ".ass")
        rendered_video = next(path for path in files if path.suffix == video.suffix)
        if len({path.stem for path in files}) != 1:
            raise ValueError("subtitle artifacts do not share a stem")
    except (OSError, ValueError, StopIteration) as exc:
        raise RenderingError(
            "multisubs did not produce a complete SRT, ASS, and video set"
        ) from exc
    return SubtitleArtifacts(
        cues_json_path=cues_path.resolve(strict=True),
        srt_path=srt_path,
        ass_path=ass_path,
        video_path=rendered_video,
        provider_version=version,
        template_requested=template,
        template_resolved=template or "default",
    )


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
        return _render_subtitles(
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
        backend: str = "whisperx",
    ) -> Transcript:
        """Return a project-owned transcript from one public provider call."""
        artifact = self._transcribe_to_artifact(
            video_path,
            language=language,
            model=model,
            workspace=workspace,
            backend=backend,
        )
        return _normalize_artifact(artifact)

    def _transcribe_to_artifact(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
        backend: str,
    ) -> _TranscriptionArtifact:
        """Generate source artifacts inside the workspace and verify the JSON."""
        try:
            provider = importlib.import_module("multisubs")
            generate = provider.generate_transcriptions
        except Exception as exc:
            raise TranscriptionError(
                "multisubs public transcription API is unavailable; "
                "check the multisubs installation"
            ) from exc
        if not callable(generate):
            raise TranscriptionError("multisubs public transcription API is invalid")
        version = self.version()

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
                asr_backend=backend,
                **model_options,
            )
        except Exception as exc:
            raise TranscriptionError(
                "multisubs could not transcribe the source; check its audio, "
                "language, ASR backend dependencies, and model compatibility"
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

        return _TranscriptionArtifact(
            json_path=resolved_json,
            provider_version=version,
            language_requested=language,
        )
