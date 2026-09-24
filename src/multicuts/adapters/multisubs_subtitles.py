"""ASR-free subtitle rendering through the supported multisubs CLI contract."""

from __future__ import annotations

import importlib.metadata
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from multicuts.errors import RenderingError
from multicuts.models import ClipTranscript, ClipTranscriptWord


@dataclass(frozen=True, slots=True)
class SubtitleArtifacts:
    """Validated outputs and provenance from one clip subtitle render."""

    cues_json_path: Path
    srt_path: Path
    ass_path: Path
    video_path: Path
    provider_version: str
    template_requested: str | None
    template_resolved: str


def _require_provider_version() -> str:
    try:
        version = importlib.metadata.version("multisubs")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RenderingError(
            "multisubs is unavailable; install the configured multisubs 4.3 release"
        ) from exc
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except (ValueError, TypeError) as exc:
        raise RenderingError(f"Unsupported multisubs version: {version}") from exc
    if major != 4 or minor < 3:
        raise RenderingError(
            f"multisubs {version} cannot render timed-cue JSON; "
            "install version 4.3 or newer"
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
            "multisubs 4.3 cannot infer missing word times"
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
                    {
                        "start": word.start,
                        "end": word.end,
                        "text": word.text.strip(),
                    }
                    for word in words
                ],
            }
        )
    if not cues or len(assigned) != len(clip.words):
        raise RenderingError(
            "Clip words cannot be mapped to timed source segments for subtitles"
        )
    return {"schema_version": 1, "language": language, "cues": cues}


def render_subtitles(
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
