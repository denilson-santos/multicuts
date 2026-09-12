"""Hermetic tests for the public multisubs transcription boundary."""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.errors import TranscriptionError
from multicuts.models import Transcript, TranscriptSegment, Word

TRANSCRIPT_FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "multisubs_v4_1_transcript.json"
)


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    generate: Callable[..., object] | None,
    *,
    version: str = "4.1.0",
) -> None:
    provider = ModuleType("multisubs")
    provider.__dict__["__version__"] = version
    if generate is not None:
        provider.__dict__["generate_transcriptions"] = generate
    monkeypatch.setitem(sys.modules, "multisubs", provider)


def _write_artifacts(
    output_dir: Path,
    *,
    json_text: str = '{"segments": [{"text": "hello"}]}',
) -> tuple[str, str, str]:
    json_path = output_dir / "source.json"
    srt_path = output_dir / "source.srt"
    ass_path = output_dir / "source.ass"
    json_path.write_text(json_text, encoding="utf-8")
    srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    ass_path.write_text("[Script Info]\n", encoding="utf-8")
    return str(json_path), str(srt_path), str(ass_path)


def _transcribe_json(
    json_text: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    language: str | None = None,
) -> Transcript:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        return _write_artifacts(output_dir, json_text=json_text)

    _install_provider(monkeypatch, generate)
    return MultisubsAdapter().transcribe(
        tmp_path / "source.mp4",
        language=language,
        model="default",
        workspace=tmp_path / "run",
    )


@pytest.mark.parametrize("requested_language", [None, "pt"])
def test_normalizes_public_json_without_losing_timing_or_text(
    requested_language: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = _transcribe_json(
        TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"),
        tmp_path,
        monkeypatch,
        language=requested_language,
    )

    assert transcript.language_requested == requested_language
    assert transcript.language_detected == "pt"
    assert transcript.duration == 2.0
    assert transcript.text == "Olá mundo. 世界!"
    assert transcript.segments == (
        TranscriptSegment("Olá mundo.", 0.0, 1.0),
        TranscriptSegment("世界!", 1.2, 2.0),
    )
    assert transcript.words == (
        Word("Olá", 0.125, 0.475, 0.97),
        Word("mundo.", 0.5, 1.0),
        Word("世界!", None, None),
    )
    assert (transcript.provider, transcript.provider_version) == (
        "multisubs",
        "4.1.0",
    )


def test_missing_segment_timing_remains_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"))
    segment = payload["transcription"]["segments"][1]
    del segment["start"]
    del segment["end"]

    transcript = _transcribe_json(
        json.dumps(payload, ensure_ascii=False), tmp_path, monkeypatch
    )

    assert transcript.segments[1] == TranscriptSegment("世界!", None, None)


@pytest.mark.parametrize(
    "case, expected",
    [
        ("schema", "schema version"),
        ("language", "detected language"),
        ("duration", "duration"),
        ("text", "transcription text"),
        ("segments", "segments"),
        ("segment_interval", "segment 0"),
        ("partial_segment_interval", "segment 0 timing"),
        ("word_interval", "word 0 timing"),
        ("word_text", "word 0 text"),
        ("word_score", "word 0 score"),
    ],
)
def test_rejects_invalid_consumed_json_fields(
    case: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"))
    if case == "schema":
        payload["schema_version"] = 4
    elif case == "language":
        payload["metadata"]["language"] = ""
    elif case == "duration":
        payload["metadata"]["duration"] = 0
    elif case == "text":
        payload["transcription"]["text"] = ""
    elif case == "segments":
        payload["transcription"]["segments"] = []
    else:
        segment = payload["transcription"]["segments"][0]
        word = segment["words"][0]
        if case == "segment_interval":
            segment["end"] = -1
        elif case == "partial_segment_interval":
            del segment["end"]
        elif case == "word_interval":
            del word["end"]
        elif case == "word_text":
            word["word"] = ""
        elif case == "word_score":
            word["score"] = "high"

    with pytest.raises(TranscriptionError, match=expected):
        _transcribe_json(json.dumps(payload, ensure_ascii=False), tmp_path, monkeypatch)


def test_non_finite_json_number_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"))
    payload["metadata"]["duration"] = float("nan")

    with pytest.raises(TranscriptionError, match="readable JSON transcript"):
        _transcribe_json(json.dumps(payload), tmp_path, monkeypatch)


def test_auto_language_and_default_model_use_public_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Path, dict[str, object]]] = []

    def generate(
        input_path: Path, output_dir: Path, **kwargs: object
    ) -> tuple[str, str, str]:
        calls.append((input_path, output_dir, kwargs))
        return _write_artifacts(output_dir)

    _install_provider(monkeypatch, generate)
    video_path = tmp_path / "source.mp4"
    result = MultisubsAdapter().transcribe_to_artifact(
        video_path,
        language=None,
        model="default",
        workspace=tmp_path / "run",
    )

    assert result.json_path == (tmp_path / "run/multisubs/source.json").resolve()
    assert result.provider_version == "4.1.0"
    assert result.language_requested is None
    assert calls == [
        (
            video_path,
            (tmp_path / "run/multisubs").resolve(),
            {"lang": None, "task": "transcribe"},
        )
    ]


def test_explicit_language_and_model_are_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options: list[dict[str, object]] = []

    def generate(
        _input_path: Path, output_dir: Path, **kwargs: object
    ) -> tuple[str, str, str]:
        options.append(kwargs)
        return _write_artifacts(output_dir)

    _install_provider(monkeypatch, generate)

    result = MultisubsAdapter().transcribe_to_artifact(
        tmp_path / "source.mp4",
        language="pt",
        model="large-v3",
        workspace=tmp_path / "run",
    )

    assert result.language_requested == "pt"
    assert options == [{"lang": "pt", "task": "transcribe", "model_name": "large-v3"}]


def test_provider_failure_is_chained_without_leaking_provider_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = RuntimeError("private video path and provider details")

    def generate(_input_path: Path, _output_dir: Path, **_kwargs: object) -> None:
        raise failure

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="could not transcribe") as caught:
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )
    assert caught.value.__cause__ is failure
    assert "private video path" not in str(caught.value)


def test_missing_public_api_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, None)

    with pytest.raises(TranscriptionError, match="public transcription API"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_unavailable_provider_is_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = ModuleNotFoundError("private dependency detail")

    def unavailable(_name: str) -> ModuleType:
        raise failure

    monkeypatch.setattr(
        "multicuts.adapters.multisubs.importlib.import_module", unavailable
    )

    with pytest.raises(TranscriptionError, match="public transcription API") as caught:
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )
    assert caught.value.__cause__ is failure
    assert "private dependency detail" not in str(caught.value)


@pytest.mark.parametrize("generated", [None, (), ("only.json",), (1, 2, 3)])
def test_invalid_provider_return_is_rejected(
    generated: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(_input_path: Path, _output_dir: Path, **_kwargs: object) -> object:
        return generated

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="invalid artifact paths"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


@pytest.mark.parametrize("json_text", ["", "{invalid", "{}", "[]"])
def test_missing_or_invalid_json_cannot_be_successful(
    json_text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        return _write_artifacts(output_dir, json_text=json_text)

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="JSON transcript"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_missing_companion_artifact_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        paths = _write_artifacts(output_dir)
        (output_dir / "source.ass").unlink()
        return paths

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="readable JSON transcript"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_missing_json_artifact_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        paths = _write_artifacts(output_dir)
        (output_dir / "source.json").unlink()
        return paths

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="readable JSON transcript"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_provider_output_cannot_escape_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        paths = _write_artifacts(output_dir)
        outside = tmp_path / "outside.json"
        outside.write_text('{"text": "hello"}', encoding="utf-8")
        return str(outside), paths[1], paths[2]

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="inside its workspace"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )
