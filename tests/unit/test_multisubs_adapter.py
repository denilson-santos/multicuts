"""Hermetic transcription and subtitle contracts for MultisubsAdapter."""

import json
import os
import sys
from collections.abc import Callable
from dataclasses import replace
from importlib import metadata
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace

import pytest

from multicuts.adapters import multisubs
from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.cache import (
    load_transcript,
    save_transcript,
    transcript_content_fingerprint,
)
from multicuts.errors import RenderingError, TranscriptionError
from multicuts.models import (
    ClipTranscript,
    ClipTranscriptSegment,
    ClipTranscriptWord,
    Transcript,
    TranscriptSegment,
    Word,
)

TRANSCRIPT_FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "multisubs_v4_1_transcript.json"
)


@pytest.fixture(autouse=True)
def _semantic_provider_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ModuleType("multisubs")
    provider.__dict__["transcribe_speech"] = lambda *_args, **_kwargs: None
    provider.__dict__["render_transcript"] = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "multisubs", provider)


def test_provider_version_uses_distribution_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metadata, "version", lambda _name: "4.2.0")

    assert MultisubsAdapter().version() == "4.2.0"


def test_missing_provider_version_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_name: str) -> str:
        raise metadata.PackageNotFoundError("multisubs")

    monkeypatch.setattr(metadata, "version", missing)

    with pytest.raises(TranscriptionError, match="check the multisubs installation"):
        MultisubsAdapter().version()


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    transcribe: Callable[..., object] | None,
    *,
    version: str = "4.2.0",
) -> None:
    provider = ModuleType("multisubs")
    monkeypatch.setattr(metadata, "version", lambda _name: version)
    provider.__dict__["__version__"] = version
    if transcribe is not None:
        provider.__dict__["transcribe_speech"] = transcribe
    monkeypatch.setitem(sys.modules, "multisubs", provider)

    def missing_distribution(name: str) -> metadata.Distribution:
        raise metadata.PackageNotFoundError(name)

    def missing_library(_name: str, *, mode: int) -> None:
        raise OSError("Native libraries are unavailable in this hermetic test")

    monkeypatch.setattr(metadata, "distribution", missing_distribution)
    monkeypatch.setattr(multisubs.ctypes, "CDLL", missing_library)


def _semantic_document(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        language=payload.get("metadata", {}).get("language"),
        task=payload.get("metadata", {}).get("task"),
        duration=payload.get("metadata", {}).get("duration"),
        asr_backend="whisperx",
        model_name="turbo",
        full_text=payload.get("transcription", {}).get("text"),
        segments=payload.get("transcription", {}).get("segments"),
    )


def _fixture_document(*, json_text: str | None = None) -> SimpleNamespace:
    return _semantic_document(
        json.loads(
            TRANSCRIPT_FIXTURE.read_text(encoding="utf-8")
            if json_text is None
            else json_text
        )
    )


def _transcribe_json(
    json_text: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    language: str | None = None,
) -> Transcript:
    def transcribe(_input_path: Path, **_kwargs: object) -> SimpleNamespace:
        return _fixture_document(json_text=json_text)

    _install_provider(monkeypatch, transcribe)
    return MultisubsAdapter().transcribe(
        tmp_path / "source.mp4",
        language=language,
        model="default",
        workspace=tmp_path / "run",
    )


@pytest.mark.parametrize("requested_language", [None, "pt"])
def test_normalizes_public_semantic_document_without_losing_timing_or_text(
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
        Word("Olá", 0.125, 0.475, 0.97, source_segment_index=0),
        Word("mundo.", 0.5, 1.0, source_segment_index=0),
        Word("世界!", None, None, source_segment_index=1),
    )
    assert (transcript.provider, transcript.provider_version) == (
        "multisubs",
        "4.2.0",
    )


def test_public_semantic_mapping_and_tuple_fields_are_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _fixture_document()
    document.segments = tuple(
        MappingProxyType(
            {
                **segment,
                "words": tuple(MappingProxyType(word) for word in segment["words"]),
            }
        )
        for segment in document.segments
    )
    _install_provider(monkeypatch, lambda *_args, **_kwargs: document)
    transcript = MultisubsAdapter().transcribe(
        tmp_path / "source.mp4",
        language=None,
        model="default",
        workspace=tmp_path / "work",
    )
    assert transcript.segments[0].text == "Olá mundo."
    assert len(transcript.words) == 3
    assert transcript.words[0].confidence == 0.97


def test_point_word_normalization_and_cache_preserve_asr_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"))
    payload["transcription"]["segments"][0]["words"][0] = {
        "word": "Olá",
        "start": 0.125,
        "end": 0.125,
        "score": 0.99609375,
    }
    transcript = _transcribe_json(json.dumps(payload), tmp_path, monkeypatch)
    assert transcript.words[0] == Word("Olá", 0.125, 0.125, 0.99609375, 0)
    cache_path = tmp_path / "cache.json"
    save_transcript(cache_path, transcript, "test-key")
    restored = load_transcript(cache_path, "test-key")
    assert restored is not None
    assert restored == transcript
    assert transcript_content_fingerprint(restored) == transcript_content_fingerprint(
        transcript
    )


def test_transcript_cache_accepts_legacy_words_without_segment_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = _transcribe_json(TRANSCRIPT_FIXTURE.read_text(), tmp_path, monkeypatch)
    cache_path = tmp_path / "cache.json"
    save_transcript(cache_path, transcript, "test-key")
    payload = json.loads(cache_path.read_text())
    for word in payload["transcript"]["words"]:
        del word["source_segment_index"]
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    restored = load_transcript(cache_path, "test-key")
    assert restored is not None
    assert restored.words == tuple(
        replace(word, source_segment_index=None) for word in transcript.words
    )


@pytest.mark.parametrize("parent", [-1, 2, True, "0"])
def test_transcript_cache_rejects_invalid_word_segment_indexes(
    parent: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = _transcribe_json(TRANSCRIPT_FIXTURE.read_text(), tmp_path, monkeypatch)
    cache_path = tmp_path / "cache.json"
    save_transcript(cache_path, transcript, "test-key")
    payload = json.loads(cache_path.read_text())
    payload["transcript"]["words"][0]["source_segment_index"] = parent
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_transcript(cache_path, "test-key") is None


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
        ("task", "task"),
        ("language", "detected language"),
        ("duration", "duration"),
        ("text", "transcription text"),
        ("segments", "segments"),
        ("segment_interval", "segment 0"),
        ("partial_segment_interval", "segment 0 timing"),
        ("word_interval", "word 0 end"),
        ("reversed_word_interval", "word 0"),
        ("word_text", "word 0 text"),
        ("word_score", "word 0 score"),
    ],
)
def test_rejects_invalid_consumed_semantic_fields(
    case: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"))
    if case == "task":
        payload["metadata"]["task"] = "translate"
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
            word["end"] = "invalid"
        elif case == "reversed_word_interval":
            word["end"] = 0.0
        elif case == "word_text":
            word["word"] = ""
        elif case == "word_score":
            word["score"] = "high"

    with pytest.raises(TranscriptionError, match=expected):
        _transcribe_json(json.dumps(payload, ensure_ascii=False), tmp_path, monkeypatch)


def test_non_finite_semantic_number_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"))
    payload["metadata"]["duration"] = float("nan")

    with pytest.raises(TranscriptionError, match="duration"):
        _transcribe_json(json.dumps(payload), tmp_path, monkeypatch)


def test_auto_language_and_default_model_use_public_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, dict[str, object]]] = []

    def transcribe(input_path: Path, **kwargs: object) -> SimpleNamespace:
        calls.append((input_path, kwargs))
        return _fixture_document()

    _install_provider(monkeypatch, transcribe)
    video_path = tmp_path / "source.mp4"
    result = MultisubsAdapter().transcribe(
        video_path,
        language=None,
        model="default",
        workspace=tmp_path / "run",
    )

    assert (tmp_path / "run/multisubs/transcript.json").is_file()
    assert result.provider_version == "4.2.0"
    assert result.language_requested is None
    assert calls == [
        (
            video_path,
            {"lang": None, "task": "transcribe", "asr_backend": "whisperx"},
        )
    ]


def test_transcript_provenance_matches_cache_provider_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def transcribe(_input_path: Path, **_kwargs: object) -> SimpleNamespace:
        return _fixture_document()

    _install_provider(monkeypatch, transcribe, version="4.3.0")
    sys.modules["multisubs"].__dict__["__version__"] = "different"
    adapter = MultisubsAdapter()

    transcript = adapter.transcribe(
        tmp_path / "source.mp4",
        language=None,
        model="default",
        workspace=tmp_path / "run",
    )

    assert transcript.provider_version == adapter.version() == "4.3.0"


@pytest.mark.parametrize(
    ("backend", "model"),
    [
        ("whisperx", "turbo"),
        ("faster-whisper", "large-v3"),
        ("parakeet", "nvidia/parakeet-tdt-0.6b-v3"),
        ("qwen", "Qwen/Qwen3-ASR-1.7B-hf"),
    ],
)
def test_explicit_language_backend_and_model_are_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str, model: str
) -> None:
    options: list[dict[str, object]] = []

    def transcribe(_input_path: Path, **kwargs: object) -> SimpleNamespace:
        options.append(kwargs)
        return _fixture_document()

    _install_provider(monkeypatch, transcribe)

    result = MultisubsAdapter().transcribe(
        tmp_path / "source.mp4",
        language="pt",
        model=model,
        backend=backend,
        workspace=tmp_path / "run",
    )

    assert result.language_requested == "pt"
    assert options == [
        {
            "lang": "pt",
            "task": "transcribe",
            "asr_backend": backend,
            "model_name": model,
        }
    ]


def test_provider_failure_is_chained_without_leaking_provider_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = RuntimeError("private video path and provider details")

    def transcribe(_input_path: Path, **_kwargs: object) -> None:
        raise failure

    _install_provider(monkeypatch, transcribe)

    with pytest.raises(TranscriptionError, match="could not transcribe") as caught:
        MultisubsAdapter().transcribe(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )
    assert caught.value.__cause__ is failure
    assert "private video path" not in str(caught.value)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            RuntimeError("Library libcublas.so.12 is not found or cannot be loaded"),
            "NVIDIA cuBLAS (CUDA 12)",
        ),
        (
            OSError("libcudnn_ops.so.9: cannot open shared object file"),
            "NVIDIA cuDNN 9",
        ),
        (
            RuntimeError("Could not load cudnn64_9.dll"),
            "NVIDIA cuDNN 9",
        ),
        (
            ModuleNotFoundError("No module named 'private dependency'"),
            "matching optional extra from the pinned multisubs wheel",
        ),
    ],
)
@pytest.mark.parametrize("chaining", ["cause", "context"])
def test_known_setup_failures_are_actionable_without_leaking_provider_details(
    failure: Exception,
    expected: str,
    chaining: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = RuntimeError("private video path; token=private-token")
    if chaining == "cause":
        wrapper.__cause__ = failure
    else:
        wrapper.__context__ = failure

    def transcribe(_input_path: Path, **_kwargs: object) -> None:
        raise wrapper

    _install_provider(monkeypatch, transcribe)
    with pytest.raises(TranscriptionError) as caught:
        MultisubsAdapter().transcribe(
            tmp_path / "source.mp4",
            language="pt",
            backend="faster-whisper",
            model="turbo",
            workspace=tmp_path / "run",
        )
    assert expected in str(caught.value)
    assert "see README installation" in str(caught.value)
    assert "private" not in str(caught.value)
    assert caught.value.__cause__ is wrapper


@pytest.mark.parametrize("library_path", [None, "/custom/cuda"])
def test_faster_whisper_loads_registered_cuda_wheels_before_one_asr_call(
    library_path: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def transcribe(_source: Path, **_kwargs: object) -> SimpleNamespace:
        events.append("ASR")
        return _fixture_document()

    _install_provider(monkeypatch, transcribe)
    monkeypatch.setattr(multisubs.sys, "platform", "linux")
    if library_path is None:
        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    else:
        monkeypatch.setenv("LD_LIBRARY_PATH", library_path)
    libraries = (
        ("cublas", "libcublasLt.so.12"),
        ("cublas", "libcublas.so.12"),
        ("cudnn", "libcudnn.so.9"),
    )
    root = tmp_path / "site-packages"
    for folder, library in libraries:
        path = root / "nvidia" / folder / "lib" / library
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    distribution = metadata.PathDistribution(root / "runtime.dist-info")
    monkeypatch.setattr(metadata, "distribution", lambda _name: distribution)

    def load(name: str, *, mode: int) -> object:
        assert mode == multisubs.ctypes.RTLD_GLOBAL
        events.append(name)
        if not Path(name).is_absolute():
            raise OSError("Not visible through system library lookup")
        return object()

    monkeypatch.setattr(multisubs.ctypes, "CDLL", load)
    transcript = MultisubsAdapter().transcribe(
        tmp_path / "source.mp4",
        language="pt",
        backend="faster-whisper",
        model="turbo",
        workspace=tmp_path / "work",
    )
    assert transcript.words
    assert events == [
        value
        for folder, library in libraries
        for value in (library, str(root / "nvidia" / folder / "lib" / library))
    ] + ["ASR"]
    assert os.environ.get("LD_LIBRARY_PATH") == library_path


def test_faster_whisper_keeps_available_system_cuda_libraries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded: list[str] = []

    def transcribe(_source: Path, **_kwargs: object) -> SimpleNamespace:
        return _fixture_document()

    _install_provider(monkeypatch, transcribe)
    monkeypatch.setattr(multisubs.sys, "platform", "linux")

    def load(name: str, *, mode: int) -> object:
        loaded.append(name)
        return object()

    def unexpected_lookup(_name: str) -> metadata.Distribution:
        raise AssertionError("Available system libraries must retain precedence")

    monkeypatch.setattr(multisubs.ctypes, "CDLL", load)
    monkeypatch.setattr(metadata, "distribution", unexpected_lookup)
    MultisubsAdapter().transcribe(
        tmp_path / "source.mp4",
        language="pt",
        backend="faster-whisper",
        model="turbo",
        workspace=tmp_path / "work",
    )
    assert loaded == ["libcublasLt.so.12", "libcublas.so.12", "libcudnn.so.9"]


@pytest.mark.parametrize(
    ("backend", "platform"),
    [
        ("whisperx", "linux"),
        ("parakeet", "linux"),
        ("qwen", "linux"),
        ("faster-whisper", "darwin"),
        ("faster-whisper", "win32"),
    ],
)
def test_cuda_preloading_is_scoped_to_faster_whisper_on_linux(
    backend: str,
    platform: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def transcribe(_source: Path, **_kwargs: object) -> SimpleNamespace:
        return _fixture_document()

    _install_provider(monkeypatch, transcribe)
    monkeypatch.setattr(multisubs.sys, "platform", platform)

    def unexpected_load(_name: str, *, mode: int) -> None:
        raise AssertionError("CUDA libraries must not be loaded for this runtime")

    monkeypatch.setattr(multisubs.ctypes, "CDLL", unexpected_load)
    assert (
        MultisubsAdapter()
        .transcribe(
            tmp_path / "source.mp4",
            language="pt",
            backend=backend,
            model="default",
            workspace=tmp_path / "work",
        )
        .words
    )


@pytest.mark.parametrize("wheel_state", ["missing", "empty", "broken"])
def test_optional_cuda_libraries_do_not_prevent_cpu_transcription(
    wheel_state: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    def transcribe(_source: Path, **_kwargs: object) -> SimpleNamespace:
        calls.append("ASR")
        return _fixture_document()

    _install_provider(monkeypatch, transcribe)
    monkeypatch.setattr(multisubs.sys, "platform", "linux")
    if wheel_state != "missing":
        root = tmp_path / "site-packages"
        distribution = metadata.PathDistribution(root / "runtime.dist-info")
        monkeypatch.setattr(metadata, "distribution", lambda _name: distribution)
        if wheel_state == "broken":
            for folder, library in (
                ("cublas", "libcublasLt.so.12"),
                ("cublas", "libcublas.so.12"),
                ("cudnn", "libcudnn.so.9"),
            ):
                path = root / "nvidia" / folder / "lib" / library
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

    def load(_name: str, *, mode: int) -> None:
        raise OSError("private path; token=private-token")

    monkeypatch.setattr(multisubs.ctypes, "CDLL", load)
    with caplog.at_level("DEBUG", logger="multicuts.adapters.multisubs"):
        transcript = MultisubsAdapter().transcribe(
            tmp_path / "source.mp4",
            language="pt",
            backend="faster-whisper",
            model="turbo",
            workspace=tmp_path / "work",
        )
    assert transcript.words
    assert calls == ["ASR"]
    assert "private" not in caplog.text


def test_unknown_cyclic_provider_failure_keeps_the_safe_generic_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = RuntimeError("private provider failure")
    failure.__cause__ = failure

    def transcribe(_input_path: Path, **_kwargs: object) -> None:
        raise failure

    _install_provider(monkeypatch, transcribe)
    with pytest.raises(TranscriptionError, match="could not transcribe") as caught:
        MultisubsAdapter().transcribe(
            tmp_path / "source.mp4",
            language=None,
            model="turbo",
            workspace=tmp_path / "run",
        )
    assert "private" not in str(caught.value)
    assert caught.value.__cause__ is failure


def test_missing_public_api_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, None)

    with pytest.raises(TranscriptionError, match="public semantic transcription API"):
        MultisubsAdapter().transcribe(
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

    with pytest.raises(
        TranscriptionError, match="public semantic transcription API"
    ) as caught:
        MultisubsAdapter().transcribe(
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
    def transcribe(_input_path: Path, **_kwargs: object) -> object:
        return generated

    _install_provider(monkeypatch, transcribe)

    with pytest.raises(TranscriptionError, match="speech transcript"):
        MultisubsAdapter().transcribe(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_workspace_cannot_escape_its_configured_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(
        monkeypatch, lambda *_args, **_kwargs: pytest.fail("ASR must not start")
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "multisubs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(TranscriptionError, match="workspace must stay"):
        MultisubsAdapter().transcribe(
            tmp_path / "source.mp4", language=None, model="default", workspace=workspace
        )


def _clip(*, complete: bool = True) -> ClipTranscript:
    return ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=2.0,
        source_start=4.0,
        source_end=6.0,
        source_duration=10.0,
        text="Olá mundo.",
        segments=(ClipTranscriptSegment("Olá mundo.", 0.2, 1.8, 0),),
        words=(
            ClipTranscriptWord("Olá", 0.2, 0.7, None, 0, 0),
            ClipTranscriptWord("mundo.", 0.8, 1.8, None, 1, 0),
        ),
        provider="multisubs",
        provider_version="5.0.0",
        word_timing_complete=complete,
    )


@pytest.mark.parametrize(
    "text,tokens,intervals",
    [
        (
            "Olá de novo.",
            ("Olá", "de", "novo."),
            ((0.2, 0.2), (0.8, 1.2), (1.3, 1.8)),
        ),
        (
            "Olá de novo.",
            ("Olá", "de", "novo."),
            ((0.2, 0.7), (0.8, 0.8), (1.0, 1.8)),
        ),
        (
            "Olá de novo.",
            ("Olá", "de", "novo."),
            ((0.2, 0.7), (0.8, 1.2), (1.8, 1.8)),
        ),
        (
            "Olá de novo.",
            ("Olá", "de", "novo."),
            ((0.2, 0.2), (0.8, 0.8), (1.8, 1.8)),
        ),
        (
            "Olá de novo.",
            ("Olá", "de", "novo."),
            ((0.7, 0.7), (0.7, 0.7), (0.7, 0.7)),
        ),
        (
            "a b a  b",
            ("a", "b", "a", "b"),
            ((0.2, 0.5), (0.5, 0.7), (0.8, 1.2), (1.8, 1.8)),
        ),
        (
            "你好世界!",
            ("你好", "世界", "!"),
            ((0.2, 0.2), (0.7, 0.7), (0.8, 1.8)),
        ),
    ],
)
def test_semantic_segments_preserve_every_point_word_and_its_observed_timing(
    text: str,
    tokens: tuple[str, ...],
    intervals: tuple[tuple[float, float], ...],
) -> None:
    words = tuple(
        ClipTranscriptWord(token, start, end, 0.9, index, 0)
        for index, (token, (start, end)) in enumerate(
            zip(tokens, intervals, strict=True)
        )
    )
    clip = replace(
        _clip(),
        text=text,
        segments=(ClipTranscriptSegment(text, 0.2, 1.8, 0),),
        words=words,
    )
    cues = multisubs._speech_transcript(clip)["segments"]
    assert cues == [
        {
            "start": 0.2,
            "end": 1.8,
            "text": text,
            "words": [
                {"start": start, "end": end, "word": token, "score": 0.9}
                for token, (start, end) in zip(tokens, intervals, strict=True)
            ],
        }
    ]
    assert clip.words == words


def _rendered_artifacts(output_dir: Path) -> SimpleNamespace:
    paths = [output_dir / f"raw-pt{suffix}" for suffix in (".srt", ".ass", ".mp4")]
    for path in paths:
        path.write_bytes(b"rendered")
    return SimpleNamespace(srt_path=paths[0], ass_path=paths[1], video_path=paths[2])


def test_public_render_api_receives_clip_local_speech_and_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_video = tmp_path / "raw.mp4"
    raw_video.write_bytes(b"raw video")
    monkeypatch.setattr(metadata, "version", lambda _name: "5.0.0")
    calls = []

    def render(speech, video, output_dir, **options):
        calls.append((speech, video, options))
        options["progress"]("Warning: word effects suppressed.")
        return _rendered_artifacts(output_dir)

    monkeypatch.setattr(sys.modules["multisubs"], "render_transcript", render)
    template_dir = tmp_path / "templates"
    result = MultisubsAdapter().subtitle_clip(
        raw_video,
        _clip(),
        template="amber-word",
        template_dir=template_dir,
        workspace=tmp_path / "work",
    )
    payload = json.loads(result.transcript_json_path.read_text())
    assert payload == multisubs._speech_transcript(_clip())
    assert payload["schema_version"] == 1 and payload["task"] == "transcribe"
    assert payload["asr_backend"] == "whisperx" and payload["model_name"] == "turbo"
    assert payload["segments"][0]["words"][0] == {
        "word": "Olá",
        "start": 0.2,
        "end": 0.7,
        "score": None,
    }
    assert len(calls) == 1
    speech, video, options = calls[0]
    assert speech == payload and video == raw_video
    assert (
        options["template"] == "amber-word" and options["template_dir"] == template_dir
    )
    assert "word effects suppressed" in caplog.text
    assert result.video_path.read_bytes() == b"rendered"
    assert result.provider_version == "5.0.0"
    assert result.template_resolved == "amber-word"


def test_partial_segment_keeps_selected_word_text_without_outside_words() -> None:
    clip = ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=1.0,
        source_start=4.0,
        source_end=5.0,
        source_duration=10.0,
        text="mundo.",
        segments=(ClipTranscriptSegment("Olá mundo. Adeus", 0.0, 1.0, 0),),
        words=(ClipTranscriptWord("mundo.", 0.1, 0.8, None, 1, 0),),
        provider="multisubs",
        provider_version="5.0.0",
        word_timing_complete=True,
    )

    assert multisubs._speech_transcript(clip)["segments"] == [
        {
            "start": 0.0,
            "end": 1.0,
            "text": " mundo. ",
            "words": [{"start": 0.1, "end": 0.8, "word": "mundo.", "score": None}],
        }
    ]


def test_long_asr_segment_is_submitted_as_one_timed_cue() -> None:
    tokens = (
        "Lembrando que a Bianquinha ela tá se apegando muito a essa treta do Felca aí"
    ).split()
    words = tuple(
        ClipTranscriptWord(token, index * 0.25, (index + 1) * 0.25, None, index, 0)
        for index, token in enumerate(tokens)
    )
    clip = ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=5.0,
        source_start=10.0,
        source_end=15.0,
        source_duration=30.0,
        text=" ".join(tokens),
        segments=(ClipTranscriptSegment(" ".join(tokens), 0.0, 5.0, 0),),
        words=words,
        provider="multisubs",
        provider_version="5.0.0",
        word_timing_complete=True,
    )

    cues = multisubs._speech_transcript(clip)["segments"]

    assert cues == [
        {
            "start": 0.0,
            "end": 5.0,
            "text": " ".join(tokens),
            "words": [
                {
                    "start": word.start,
                    "end": word.end,
                    "word": word.text,
                    "score": word.confidence,
                }
                for word in words
            ],
        }
    ]


@pytest.mark.parametrize(
    "words",
    [
        (),
        (
            ClipTranscriptWord(" Olá", 0.2, None, None, 0, 0),
            ClipTranscriptWord(" mundo.", None, 1.8, None, 1, 0),
        ),
    ],
)
def test_missing_word_timing_and_language_reach_native_fallback(
    words,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_video = tmp_path / "raw.mp4"
    raw_video.write_bytes(b"raw")
    monkeypatch.setattr(metadata, "version", lambda _name: "5.0.0")

    def render(speech, video, output_dir, **options):
        assert speech["language"] is None
        assert speech["segments"][0]["text"] == " Olá mundo."
        assert len(speech["segments"][0]["words"]) == len(words)
        return _rendered_artifacts(output_dir)

    monkeypatch.setattr(sys.modules["multisubs"], "render_transcript", render)
    clip = replace(
        _clip(complete=False),
        language_detected=None,
        words=words,
        segments=(ClipTranscriptSegment(" Olá mundo.", 0.2, 1.8, 0),),
    )
    result = MultisubsAdapter().subtitle_clip(
        raw_video,
        clip,
        template=None,
        template_dir=None,
        workspace=tmp_path / "work",
    )
    assert result.video_path.is_file()


def test_provider_without_semantic_api_fails_before_subtitle_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, None, version="5.0.0")
    with pytest.raises(RenderingError, match="speech transcript support"):
        MultisubsAdapter().subtitle_clip(
            tmp_path / "raw.mp4",
            _clip(),
            template=None,
            template_dir=None,
            workspace=tmp_path / "work",
        )


def test_old_provider_fails_with_compatibility_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(metadata, "version", lambda _name: "4.3.0")

    with pytest.raises(RenderingError, match="install version 5"):
        MultisubsAdapter().subtitle_clip(
            tmp_path / "raw.mp4",
            _clip(),
            template=None,
            template_dir=None,
            workspace=tmp_path / "work",
        )


def test_layout_failure_identifies_template_space_without_raw_provider_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_video = tmp_path / "raw.mp4"
    raw_video.write_bytes(b"raw")
    monkeypatch.setattr(metadata, "version", lambda _name: "5.0.0")

    def render(*args, **options):
        raise ValueError(
            "private input path: cue 0 exceeds the subtitle layout envelope"
        )

    monkeypatch.setattr(sys.modules["multisubs"], "render_transcript", render)
    with pytest.raises(
        RenderingError, match="does not fit the selected template"
    ) as caught:
        MultisubsAdapter().subtitle_clip(
            raw_video,
            _clip(),
            template="yellow-pop",
            template_dir=None,
            workspace=tmp_path / "work",
        )
    assert "private input path" not in str(caught.value)


@pytest.mark.parametrize("invalid", ["missing", "outside", "empty", "mismatched"])
def test_incomplete_or_escaped_provider_output_is_rejected(
    invalid,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_video = tmp_path / "raw.mp4"
    raw_video.write_bytes(b"raw")
    monkeypatch.setattr(metadata, "version", lambda _name: "5.0.0")

    def render(speech, video, output_dir, **options):
        artifacts = _rendered_artifacts(output_dir)
        if invalid == "missing":
            artifacts.srt_path.unlink()
        elif invalid == "empty":
            artifacts.ass_path.write_bytes(b"")
        elif invalid == "outside":
            artifacts.srt_path = tmp_path / "outside.srt"
            artifacts.srt_path.write_text("caption")
        else:
            artifacts.ass_path = artifacts.ass_path.rename(output_dir / "different.ass")
        return artifacts

    monkeypatch.setattr(sys.modules["multisubs"], "render_transcript", render)
    with pytest.raises(RenderingError, match="complete SRT, ASS, and video"):
        MultisubsAdapter().subtitle_clip(
            raw_video,
            _clip(),
            template=None,
            template_dir=None,
            workspace=tmp_path / "work",
        )


def test_existing_cjk_spacing_is_preserved() -> None:
    words = [
        ClipTranscriptWord("你好", 0.0, 0.4, None, 0, 0),
        ClipTranscriptWord("世界!", 0.5, 1.0, None, 1, 0),
    ]
    assert multisubs._source_text_for_words("你好世界!", words) == "你好世界!"


def test_unassigned_words_fail_instead_of_disappearing() -> None:
    clip = ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=2.0,
        source_start=4.0,
        source_end=6.0,
        source_duration=10.0,
        text="Olá mundo.",
        segments=(ClipTranscriptSegment("Olá mundo.", 0.2, 1.8, 0),),
        words=(
            ClipTranscriptWord("Olá", 0.2, 0.7, None, 0, 0),
            ClipTranscriptWord("mundo.", 0.8, 1.8, None, 1, None),
        ),
        provider="multisubs",
        provider_version="5.0.0",
        word_timing_complete=True,
    )
    with pytest.raises(RenderingError, match="cannot be mapped"):
        multisubs._speech_transcript(clip)


@pytest.mark.parametrize("word_field", ["absent", "null", "empty", "partial"])
def test_public_speech_normalization_and_cache_preserve_missing_alignment(
    word_field: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    segment = {"text": " Olá mundo.", "start": 0.2, "end": 1.8}
    if word_field == "null":
        segment["words"] = None
    elif word_field == "empty":
        segment["words"] = []
    elif word_field == "partial":
        segment["words"] = [
            {"word": " Olá", "start": 0.2},
            {"word": " mundo.", "end": 1.8, "score": None},
        ]
    document = SimpleNamespace(
        language=None,
        task="transcribe",
        duration=1.8,
        full_text=segment["text"],
        segments=(segment,),
        asr_backend="parakeet",
        model_name="source-model",
    )
    _install_provider(monkeypatch, lambda *_args, **_kwargs: document, version="5.0.0")
    transcript = MultisubsAdapter().transcribe(
        tmp_path / "source.mp4",
        language=None,
        backend="parakeet",
        model="source-model",
        workspace=tmp_path / "asr",
    )
    assert transcript.language_detected is None
    assert transcript.segments[0].text == " Olá mundo."
    assert (transcript.asr_backend, transcript.asr_model) == (
        "parakeet",
        "source-model",
    )
    if word_field == "partial":
        assert [(w.text, w.start, w.end) for w in transcript.words] == [
            (" Olá", 0.2, None),
            (" mundo.", None, 1.8),
        ]
    else:
        assert transcript.words == ()
    cache = tmp_path / "cache.json"
    save_transcript(cache, transcript, "test-key")
    assert load_transcript(cache, "test-key") == transcript
    assert transcript_content_fingerprint(transcript) == transcript_content_fingerprint(
        replace(transcript, asr_backend="faster-whisper", asr_model="turbo")
    )


@pytest.mark.parametrize("bad_words", [False, 0, "", {}])
def test_invalid_falsy_word_collection_is_not_treated_as_missing_alignment(
    bad_words: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"))
    payload["transcription"]["segments"][0]["words"] = bad_words
    with pytest.raises(TranscriptionError, match="segment 0 words"):
        _transcribe_json(json.dumps(payload), tmp_path, monkeypatch)
