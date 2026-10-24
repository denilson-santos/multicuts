"""Hermetic checks for semantic selection, reruns, and run artifacts."""

import json
import logging
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.app_config import AppConfig
from multicuts.cli import parse_run_config
from multicuts.clips import (
    DIRECT_TITLE_PROMPT_VERSION,
    DIRECT_TITLE_SCHEMA,
    DirectClip,
    JudgedClip,
    TimedUnit,
    judgment_prompt,
    judgment_schema,
    parse_judgment,
    parse_proposals,
    select_clips,
)
from multicuts.errors import (
    AcquisitionError,
    ArtifactError,
    ConfigurationError,
    ScoringError,
)
from multicuts.models import (
    AcquiredSource,
    MediaInfo,
    RenderedVariant,
    TimeRange,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import run_pipeline
from multicuts.render import clip_transcript
from multicuts.subtitles import SubtitleOptions
from multicuts.variants import VARIANTS, OutputOptions


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls = 0
        self.settings: list[tuple[str, str]] = []
        self.inputs: list[Path] = []

    def version(self) -> str:
        return "4.3.0"

    def transcribe(
        self,
        video_path: Path,
        *,
        language: str | None,
        backend: str,
        model: str,
        workspace: Path,
    ) -> Transcript:
        self.calls += 1
        self.settings.append((backend, model))
        self.inputs.append(video_path)
        start, end = (0.0, 360.0)
        if video_path.suffix == ".range" or video_path.parent.name == "direct-source":
            start, end = map(float, json.loads(video_path.read_text(encoding="utf-8")))
        segments = tuple(
            TranscriptSegment(
                f"Point {index}.",
                max(start, index * 60.0) - start,
                min(end, (index + 1) * 60.0) - start,
            )
            for index in range(6)
            if index * 60.0 < end and (index + 1) * 60.0 > start
        )
        return Transcript(
            language_requested=language,
            language_detected="en",
            duration=end - start,
            text=" ".join(segment.text for segment in segments),
            segments=segments,
            words=(),
            provider="multisubs",
            provider_version=self.version(),
            asr_backend=backend,
            asr_model=model,
        )


class FakeBackend:
    def __init__(self, *, empty: bool = False, invalid: bool = False) -> None:
        self.calls = 0
        self.empty = empty
        self.invalid = invalid

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        self.calls += 1
        if schema == DIRECT_TITLE_SCHEMA:
            return {"title": "Direct idea"}
        if "Find every" in prompt:
            if self.invalid:
                return {"clips": [{"class": "short", "start_id": "invented"}]}
            if self.empty:
                return {"clips": []}
            return {
                "clips": [
                    {
                        "class": "short",
                        "start_id": "u0",
                        "end_id": "u1",
                        "title": "Short idea",
                        "rationale": "Complete compact point",
                    },
                    {
                        "class": "long",
                        "start_id": "u0",
                        "end_id": "u5",
                        "title": "Long idea",
                        "rationale": "Full discussion",
                    },
                ]
            }
        bounds = re.search(r"Original boundary IDs: (u\d+) through (u\d+)", prompt)
        assert bounds is not None
        return {
            "start_id": bounds.group(1),
            "end_id": bounds.group(2),
            "approved": True,
            "dimensions": {
                "hook": 80,
                "standalone_context": 80,
                "development": 80,
                "payoff": 80,
                "interest_novelty": 80,
            },
            "reason": "Strong complete idea",
        }


def _media(width: int = 1920, height: int = 1080) -> MediaInfo:
    return MediaInfo(360.0, width, height, width, height, 0, 1)


def test_scoped_render_without_captions_skips_asr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_BACKEND", "")
    monkeypatch.setenv("LLM_MODEL", "")
    config = parse_run_config(
        [
            str(tmp_path / "source.mp4"),
            "--output-dir",
            str(tmp_path / "out"),
            "--clip-full",
            "--render=all:vertical=true",
            "--subtitles=all:vertical=false",
        ]
    )
    asr = FakeTranscriber()
    result = _run(tmp_path, asr, FakeBackend(), config=config)
    assert asr.calls == 0
    (video,) = result.clip_paths
    assert video.name == "vertical.mp4"
    metadata = json.loads(video.with_suffix(".json").read_text())
    assert metadata["subtitle_files"] == []
    assert metadata["render"]["subtitles_enabled"] is False


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize(
    "reason", ["primary-disabled", "primary-unavailable", "captions"]
)
def test_conflicting_output_requests_fail_before_asr_or_ai(
    tmp_path, monkeypatch, direct, reason
):
    monkeypatch.chdir(tmp_path)
    flags = (
        ["--render", "all:horizontal", "--subtitles", "all:vertical"]
        if reason == "captions"
        else [
            "--primary",
            "horizontal",
            "--render",
            "primary" if reason == "primary-unavailable" else "all:vertical",
        ]
    )
    asr, backend = FakeTranscriber(), FakeBackend()
    media = _media(360, 640) if reason == "primary-unavailable" else _media()
    message = "Subtitle selection" if reason == "captions" else "Primary output"
    with pytest.raises(ConfigurationError, match=message):
        config = parse_run_config(
            [
                str(tmp_path / "source.mp4"),
                "--output-dir",
                str(tmp_path / "out"),
                "--llm-backend",
                "codex",
                "--llm-model",
                "test-model",
                *(["--clip-full"] if direct else []),
                *flags,
            ]
        )
        _run(tmp_path, asr, backend, config=config, source_media=media)
    assert asr.calls == backend.calls == 0
    assert not list((tmp_path / "out").rglob("*.mp4"))
    assert not list((tmp_path / "out").rglob("manifest.json"))


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("reason", ["primary", "captions"])
def test_programmatic_conflicts_fail_before_provider_validation_or_acquisition(
    tmp_path, monkeypatch, direct, reason
):
    def unexpected(*args, **kwargs):
        pytest.fail("A processing boundary ran before static validation")

    monkeypatch.setattr(
        "multicuts.pipeline.MultisubsAdapter.validate_subtitle_options", unexpected
    )
    options = (
        tuple(
            OutputOptions(kind, "vertical", enabled=True) for kind in ("short", "long")
        )
        if reason == "primary"
        else tuple(
            OutputOptions(
                kind,
                name,
                enabled=name == "horizontal",
                subtitles_enabled=name == "vertical",
            )
            for kind in ("short", "long")
            for name in ("horizontal", "vertical")
        )
    )
    config = AppConfig(
        "missing.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        full_video=direct,
        render=False,
        output_options=options,
        short_primary="horizontal" if reason == "primary" else "auto",
        long_primary="horizontal" if reason == "primary" else "auto",
        subtitles_enabled=reason == "primary",
        subtitle_options=SubtitleOptions(font_size="4%"),
    )
    with pytest.raises(ConfigurationError):
        run_pipeline(
            config,
            acquire=unexpected,
            probe=unexpected,
            raw_renderer=unexpected,
            final_renderer=unexpected,
        )
    assert not config.output_dir.exists()


def test_direct_cut_validates_caption_selection_only_against_its_actual_class(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    config = parse_run_config(
        [
            str(tmp_path / "source.mp4"),
            "--output-dir",
            str(tmp_path / "out"),
            "--clip-full",
            "--render",
            "all:vertical",
            "--subtitles",
            "short:vertical",
        ]
    )
    asr, backend = FakeTranscriber(), FakeBackend()
    with pytest.raises(ConfigurationError, match="Subtitle selection"):
        _run(tmp_path, asr, backend, config=config)
    assert asr.calls == backend.calls == 0


def test_direct_cut_ignores_explicit_primary_of_the_unused_class(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_BACKEND", "")
    monkeypatch.setenv("LLM_MODEL", "")
    config = parse_run_config(
        [
            str(tmp_path / "source.mp4"),
            "--output-dir",
            str(tmp_path / "out"),
            "--clip-full",
            "--render",
            "all:vertical",
            "--primary",
            "short=horizontal",
            "--subtitles",
            "false",
        ]
    )
    asr = FakeTranscriber()
    result = _run(tmp_path, asr, FakeBackend(), config=config)
    assert asr.calls == 0
    (video,) = result.clip_paths
    assert video.name == "vertical.mp4"
    assert video.parent.parent.name == "longs"


@pytest.mark.parametrize(("duration", "kind"), [(120, "short"), (360, "long")])
def test_direct_cut_allows_configured_styles_and_dimensions_for_an_unused_class(
    duration, kind, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_BACKEND", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setattr(
        "multicuts.pipeline.MultisubsAdapter.validate_subtitle_options",
        lambda self, **kwargs: None,
    )
    config = parse_run_config(
        [
            str(tmp_path / "source.mp4"),
            "--output-dir",
            str(tmp_path / "out"),
            "--clip-full",
            "--render=all:vertical",
            "--subtitles=all:vertical",
            "--subtitle-margin-bottom=long:vertical=20%",
            "--width=long:vertical=720",
        ]
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(
        tmp_path,
        asr,
        ai,
        config=config,
        source_media=replace(_media(), duration=duration),
    )
    assert result.outcome.value == "completed"
    assert asr.calls == 1 and ai.calls == 0
    (video,) = result.clip_paths
    metadata = json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["class"] == kind
    assert metadata["render"]["subtitle_overrides"] == (
        {"margin_bottom": "20%"} if kind == "long" else {}
    )
    assert metadata["render"]["width"] == (720 if kind == "long" else 1080)


def test_search_range_scopes_discovery_review_and_reuses_full_cache(
    tmp_path: Path,
) -> None:
    class RangeBackend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            if "Find every" in prompt:
                self.calls += 1
                ids = re.findall(r"^(u\d+) \[", prompt, re.MULTILINE)
                assert ids in (["u1", "u2", "u3"], ["u2", "u3", "u4"])
                return {
                    "clips": [
                        {
                            "class": "short",
                            "start_id": ids[0],
                            "end_id": ids[1],
                            "title": "Scoped idea",
                            "rationale": "Complete idea",
                        }
                    ]
                }
            assert "Point 0." not in prompt and "Point 5." not in prompt
            response = super().complete(prompt, schema)
            assert isinstance(response, dict)
            # Review may extend to the last in-range unit, never past it.
            response["end_id"] = "u3" if "Point 1." in prompt else "u4"
            return response

    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        search_range=TimeRange(30, 250),
        subtitles_enabled=False,
    )
    asr, ai = FakeTranscriber(), RangeBackend()
    _run(tmp_path, asr, FakeBackend(empty=True))
    first = _run(tmp_path, asr, ai, config=config)
    metadata = json.loads(first.clip_paths[0].with_suffix(".json").read_text())
    assert (metadata["start"], metadata["end"]) == (60, 240)
    manifest = json.loads(first.manifest_path.read_text())
    assert manifest["analysis"]["search_range"] == {"start": 30, "end": 250}
    assert manifest["analysis"]["timed_units"] == 3
    repeated = _run(tmp_path, asr, ai, config=config)
    assert asr.calls == 1 and ai.calls == 2
    assert json.loads(repeated.manifest_path.read_text())["analysis"]["ai_cache"] == {
        "hits": 2,
        "misses": 0,
    }
    changed = _run(
        tmp_path, asr, ai, config=replace(config, search_range=TimeRange(120, 300))
    )
    metadata = json.loads(changed.clip_paths[0].with_suffix(".json").read_text())
    assert (metadata["start"], metadata["end"]) == (120, 300)
    assert asr.calls == 1 and ai.calls == 4


def test_search_range_without_complete_units_selects_nothing(tmp_path: Path) -> None:
    asr, ai = FakeTranscriber(), FakeBackend()
    _run(tmp_path, asr, FakeBackend(empty=True))
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        search_range=TimeRange(1, 59),
        subtitles_enabled=False,
    )
    result = _run(tmp_path, asr, ai, config=config)
    assert result.clip_paths == ()
    assert ai.calls == 0


def test_search_range_rejects_ai_boundaries_outside_the_interval(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        search_range=TimeRange(60, 240),
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    with pytest.raises(ScoringError, match="unknown class or transcript ID"):
        _run(tmp_path, asr, ai, config=config)
    assert ai.calls == 1


def test_search_range_outside_media_fails_before_transcription(tmp_path: Path) -> None:
    asr, ai = FakeTranscriber(), FakeBackend()
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        search_range=TimeRange(0, 361),
    )
    with pytest.raises(ConfigurationError, match="exceeds source"):
        _run(tmp_path, asr, ai, config=config)
    assert asr.calls == ai.calls == 0


@pytest.mark.parametrize(
    "interval", [TimeRange(90.25, 180.5), TimeRange(0, 180), TimeRange(60.125, 350.5)]
)
def test_custom_cut_preserves_exact_bounds_without_ai_or_asr(
    interval: TimeRange, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_backend(*_args: object) -> None:
        pytest.fail("A direct cut must not initialize an AI backend")

    monkeypatch.setattr("multicuts.pipeline.LlmBackend", unexpected_backend)
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        clip_range=interval,
        subtitles_enabled=False,
    )
    asr, ai = FakeTranscriber(), FakeBackend(invalid=True)
    result = _run(tmp_path, asr, ai, config=config)
    assert asr.calls == ai.calls == 0
    assert len(result.clip_paths) == 1
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["selection_mode"] == "custom"
    assert manifest["requested_clip_range"] == {
        "start": interval.start,
        "end": interval.end,
    }
    assert manifest["clip_range"] == {"start": interval.start, "end": interval.end}
    assert manifest["transcription"] is None
    assert manifest["analysis"]["backend"] is None
    assert manifest["analysis"]["proposed"] == 0
    assert manifest["analysis"]["editorially_eligible"] == 0
    assert manifest["analysis"]["selected"] == 1
    assert manifest["clips"][0]["score"] is None
    assert len(manifest["clips"][0]["variants"]) == 6
    for version in manifest["clips"][0]["variants"]:
        metadata = json.loads(
            (result.manifest_path.parent / version["metadata"]).read_text()
        )
        assert metadata["schema_version"] == 2
        assert metadata["selection_mode"] == "custom"
        assert (metadata["start"], metadata["end"]) == (interval.start, interval.end)
        assert metadata["class"] == (
            "short" if interval.end - interval.start <= 180 else "long"
        )
        assert metadata["viral_potential"] is None
        assert metadata["transcript_unit_ids"] is None
        assert metadata["title"] == "source"
        assert metadata["title_generation"] is None
    report = result.report_path.read_text(encoding="utf-8")
    assert "Selection mode: `custom`" in report
    assert "Not scored (direct cut)." in report
    assert "not probabilities" not in report


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("subtitles", [False, True])
@pytest.mark.parametrize("jobs", [1, 3])
def test_direct_cuts_generate_one_title_for_all_variants(
    full: bool, subtitles: bool, jobs: int, tmp_path: Path
) -> None:
    title = "Estudar mais não é aprender mais"
    prompts: list[str] = []

    class Backend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            self.calls += 1
            assert schema == DIRECT_TITLE_SCHEMA
            prompts.append(prompt)
            return {"title": f"  {title}  "}

    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        full_video=full,
        clip_range=None if full else TimeRange(60, 120),
        subtitles_enabled=subtitles,
        editorial_context="Conversa sobre hábitos.",
        render_jobs=jobs,
    )
    asr, ai = FakeTranscriber(), Backend()
    result = _run(tmp_path, asr, ai, config=config)
    assert asr.calls == ai.calls == 1
    assert len(result.clip_paths) == 1
    assert "Do not propose, reject, score, or adjust" in prompts[0]
    assert "simple, everyday words" in prompts[0]
    assert "40–80 characters" in prompts[0]
    assert "never more than 120 characters" in prompts[0]
    assert "Conversa sobre hábitos." in prompts[0]
    assert "Point 1." in prompts[0]
    assert ("Point 0." in prompts[0]) is full
    assert ("Point 5." in prompts[0]) is full
    manifest = json.loads(result.manifest_path.read_text())
    provenance = manifest["title_generation"]
    assert provenance == {
        "backend": "codex",
        "model": "test-model",
        "effort": None,
        "prompt_version": DIRECT_TITLE_PROMPT_VERSION,
        "editorial_context": config.editorial_context,
        "cache_hit": False,
    }
    assert manifest["analysis"]["backend"] is None
    assert manifest["analysis"]["proposed"] == 0
    assert manifest["analysis"]["editorially_eligible"] == 0
    assert manifest["analysis"]["ai_cache"] == {"hits": 0, "misses": 1}
    (reference,) = manifest["clips"]
    assert reference["score"] is None
    assert len(reference["variants"]) == 6
    for variant in reference["variants"]:
        metadata = json.loads(
            (result.manifest_path.parent / variant["metadata"]).read_text()
        )
        assert metadata["title"] == title
        assert metadata["title_generation"] == provenance
        assert metadata["viral_potential"] is None
        assert (metadata["start"], metadata["end"]) == ((0, 360) if full else (60, 120))
        assert len(metadata["subtitle_files"]) == (3 if subtitles else 0)
    assert "estudar-mais-nao-e-aprender-mais" in result.clip_paths[0].parent.name
    assert title in result.report_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("full", [False, True])
def test_direct_titles_reuse_cache_and_recompute_for_context_changes(
    full: bool, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        full_video=full,
        clip_range=None if full else TimeRange(60, 120),
        subtitles_enabled=False,
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    first = _run(tmp_path, asr, ai, config=config)
    assert asr.calls == ai.calls == 1
    first_report = first.report_path.read_bytes()
    asr, ai = FakeTranscriber(), FakeBackend()
    repeated = _run(tmp_path, asr, ai, config=replace(config, render="primary"))
    assert asr.calls == ai.calls == 0
    manifest = json.loads(repeated.manifest_path.read_text())
    assert manifest["title_generation"]["cache_hit"] is True
    assert first.report_path.read_bytes() == first_report
    _run(tmp_path, asr, ai, config=replace(config, editorial_context="Study habits"))
    assert asr.calls == 0 and ai.calls == 1
    _run(tmp_path, asr, ai, config=replace(config, force_recompute=True))
    assert asr.calls == 1 and ai.calls == 2


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"title": ""},
        {"title": "  "},
        {"title": 7},
        {"title": "x" * 121},
        {"title": "Valid", "extra": "field"},
    ],
)
def test_direct_titles_reject_invalid_responses_without_publishing(
    response: object, tmp_path: Path
) -> None:
    class Backend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            self.calls += 1
            return response

    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        full_video=True,
        subtitles_enabled=False,
    )
    ai = Backend()
    with pytest.raises(ScoringError, match="invalid clip title"):
        _run(tmp_path, FakeTranscriber(), ai, config=config)
    assert ai.calls == 1
    assert not list((config.output_dir / "runs").rglob("manifest.json"))
    assert not list((config.output_dir / ".cache" / "ai").glob("*.json"))


def test_direct_titles_require_timed_interval_evidence(tmp_path: Path) -> None:
    class UnalignedTranscriber(FakeTranscriber):
        def transcribe(self, *args, **kwargs) -> Transcript:
            return replace(
                super().transcribe(*args, **kwargs),
                segments=(TranscriptSegment("Unaligned speech.", None, None),),
                words=(),
            )

    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        full_video=True,
        subtitles_enabled=False,
    )
    ai = FakeBackend()
    with pytest.raises(ScoringError, match="empty transcript"):
        _run(tmp_path, UnalignedTranscriber(), ai, config=config)
    assert ai.calls == 0


@pytest.mark.parametrize("duration", [30.0, 180.0, 180.5, 360.0])
def test_full_video_uses_media_bounds_including_silence(
    duration: float, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        full_video=True,
        subtitles_enabled=False,
        render="primary",
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    media = replace(_media(), duration=duration)
    result = _run(tmp_path, asr, ai, config=config, source_media=media)
    assert asr.calls == ai.calls == 0
    metadata = json.loads(result.clip_paths[0].with_suffix(".json").read_text())
    assert (metadata["start"], metadata["end"]) == (0, duration)
    assert metadata["class"] == ("short" if duration <= 180 else "long")
    assert metadata["selection_mode"] == "full_video"


@pytest.mark.parametrize("variant_subtitles", [False, True])
def test_custom_subtitles_cache_the_exact_cut_separately_from_full_source(
    variant_subtitles: bool, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        clip_range=TimeRange(10.25, 120.5),
        short_subtitles_enabled=not variant_subtitles,
        output_options=tuple(
            OutputOptions("short", name, subtitles_enabled=variant_subtitles)
            for name in VARIANTS
            if name != "horizontal"
        ),
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    _run(tmp_path, asr, FakeBackend(empty=True))
    first = _run(tmp_path, asr, ai, config=config)
    assert asr.calls == 2
    assert not json.loads(first.manifest_path.read_text())["transcription"]["cache_hit"]
    repeated = _run(tmp_path, asr, ai, config=config)
    assert asr.calls == 2
    assert json.loads(repeated.manifest_path.read_text())["transcription"]["cache_hit"]
    result = _run(
        tmp_path, asr, ai, config=replace(config, clip_range=TimeRange(20, 100))
    )
    assert asr.calls == 3 and ai.calls == 0
    assert asr.inputs[0] == tmp_path / "source.mp4"
    assert all(path.parent.name == "direct-source" for path in asr.inputs[1:])
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["transcription"]["cache_hit"] is False
    assert manifest["transcription"]["source_range"] == {"start": 20, "end": 100}
    for version in manifest["clips"][0]["variants"]:
        metadata = json.loads(
            (result.manifest_path.parent / version["metadata"]).read_text()
        )
        assert metadata["render"]["subtitles_enabled"] == (
            variant_subtitles
            if metadata["render"]["is_variant"]
            else not variant_subtitles
        )
    _run(tmp_path, asr, ai, config=replace(config, force_recompute=True))
    assert asr.calls == 4 and ai.calls == 0


@pytest.mark.parametrize(
    ("ratio", "variants", "square_source"),
    [
        ("vertical", False, False),
        ("square", False, False),
        ("square", False, True),
    ],
)
def test_direct_cut_skips_asr_when_captioned_variants_are_not_published(
    ratio: str, variants: bool, square_source: bool, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        clip_range=TimeRange(1, 60),
        short_primary=ratio,
        render=True if variants else "primary",
        short_subtitles_enabled=False,
        output_options=(
            OutputOptions("short", "horizontal-blur", subtitles_enabled=True),
        ),
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(
        tmp_path,
        asr,
        ai,
        config=config,
        source_media=_media(1080, 1080) if square_source else _media(),
    )
    assert asr.calls == ai.calls == 0
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["transcription"] is None
    assert len(manifest["clips"][0]["variants"]) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"clip_range": TimeRange(1, 361)},
        {"clip_range": TimeRange(1, 60), "short_render": False},
        {"full_video": True, "long_render": False},
    ],
)
def test_invalid_direct_cut_fails_before_asr(tmp_path: Path, kwargs: dict) -> None:
    config = AppConfig("source.mp4", tmp_path / "out", **kwargs)
    asr, ai = FakeTranscriber(), FakeBackend()
    with pytest.raises(ConfigurationError):
        _run(tmp_path, asr, ai, config=config)
    assert asr.calls == ai.calls == 0


@pytest.mark.parametrize("mode", ["custom", "automatic"])
@pytest.mark.parametrize("subtitles", [False, True])
@pytest.mark.parametrize("padding", [0.0, 2.0])
def test_partial_youtube_pipeline_preserves_source_times_and_caches_local_asr(
    mode: str,
    subtitles: bool,
    padding: float,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    interval = TimeRange(600.25, 720.5)
    acquisition_ranges: list[TimeRange | None] = []
    rendered: list[tuple[float, float]] = []
    transcripts: list[Transcript] = []

    def acquire(
        source: str, workspace: Path, *, time_range: TimeRange | None = None
    ) -> AcquiredSource:
        assert source == "https://youtu.be/abc123"
        assert time_range is not None
        acquisition_ranges.append(time_range)
        workspace.mkdir(parents=True)
        path = workspace / "part.mp4"
        path.write_bytes(b"part")
        return AcquiredSource(
            path,
            f"range-{time_range.start}-{time_range.end}",
            "youtube",
            "abc123",
            "Source title",
            source,
            TimeRange(time_range.start - padding, time_range.end + padding),
            1800.0,
        )

    class Transcriber(FakeTranscriber):
        def transcribe(
            self,
            video_path: Path,
            *,
            language: str | None,
            backend: str,
            model: str,
            workspace: Path,
        ) -> Transcript:
            self.calls += 1
            assert video_path.name == "part.mp4"
            return Transcript(
                language,
                "en",
                120.25 + 2 * padding,
                "First point. Second point.",
                (
                    TranscriptSegment("First point.", 0.5 + padding, 30 + padding),
                    TranscriptSegment("Second point.", 40 + padding, 110 + padding),
                ),
                (
                    Word("First", 0.5 + padding, 1 + padding, source_segment_index=0),
                    Word("point.", 1 + padding, 1 + padding, source_segment_index=0),
                    Word(
                        "Second point.",
                        40 + padding,
                        41.5 + padding,
                        source_segment_index=1,
                    ),
                ),
                "multisubs",
                self.version(),
            )

    class Backend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            if "Find every" in prompt:
                self.calls += 1
                return {
                    "clips": [
                        {
                            "class": "short",
                            "start_id": "u0",
                            "end_id": "u1",
                            "title": "Scoped idea",
                            "rationale": "Complete point",
                        }
                    ]
                }
            return super().complete(prompt, schema)

    media = replace(_media(), duration=120.25 + 2 * padding)

    def raw_renderer(source, _media, clip, config, *, output, work):
        assert source.acquired_range is not None
        assert clip.proposal.start >= source.acquired_range.start
        assert clip.proposal.end <= source.acquired_range.end
        rendered.append((clip.proposal.start, clip.proposal.end))
        output.parent.mkdir(parents=True)
        output.write_bytes(b"raw")
        return (
            output,
            replace(media, duration=clip.proposal.end - clip.proposal.start),
            "16:9",
        )

    def final_renderer(raw, _media, transcript, clip, config, *, output, work):
        if transcript is not None:
            transcripts.append(transcript)
            local = clip_transcript(transcript, clip.proposal.start, clip.proposal.end)
            assert local.words[0].start == pytest.approx(
                0.5 + padding if mode == "custom" else 0.0
            )
            assert local.words[1].start == local.words[1].end
            assert local.words[1].source_segment_index == 0
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, output)
        return output, (), None

    config = AppConfig(
        "https://youtu.be/abc123",
        tmp_path / "out",
        "codex",
        "test-model",
        clip_range=interval if mode == "custom" else None,
        search_range=interval if mode == "automatic" else None,
        subtitles_enabled=subtitles,
        render="primary",
        short_primary="horizontal",
    )
    asr, ai = Transcriber(), Backend()

    def run(current: AppConfig):
        return run_pipeline(
            current,
            acquire=acquire,
            probe=lambda _: media,
            transcriber=asr,
            backend=ai,
            raw_renderer=raw_renderer,
            final_renderer=final_renderer,
        )

    first = run(config)
    repeated = run(config)
    expected = (
        (600.25 - padding, 720.5 + padding) if mode == "custom" else (600.75, 710.25)
    )
    assert rendered == [expected, expected]
    needs_asr = subtitles or bool(config.llm_backend)
    assert asr.calls == int(needs_asr)
    assert ai.calls == (2 if mode == "automatic" else 1)
    manifest = json.loads(repeated.manifest_path.read_text())
    assert manifest["requested_clip_range"] == (
        {"start": interval.start, "end": interval.end} if mode == "custom" else None
    )
    assert manifest["clip_range"] == (
        {"start": expected[0], "end": expected[1]} if mode == "custom" else None
    )
    metadata = json.loads(first.clip_paths[0].with_suffix(".json").read_text())
    assert (metadata["start"], metadata["end"]) == expected
    warning = next(
        record.message for record in caplog.records if record.levelno == logging.WARNING
    )
    assert "Requested 600.250-720.500s" in warning
    assert f"{600.25 - padding:.3f}-{720.5 + padding:.3f}s" in warning
    if mode == "custom":
        assert "YouTube --clip-range boundaries are approximate" in warning
        assert "the final cut uses the acquired interval" in warning
    else:
        assert (
            "YouTube --search-range acquisition boundaries are approximate" in warning
        )
        assert "clip discovery stays within the requested range" in warning
    assert manifest["source"]["original_duration"] == 1800
    assert manifest["source"]["acquired_duration"] == 120.25 + 2 * padding
    assert manifest["source"]["acquired_range"] == {
        "start": 600.25 - padding,
        "end": 720.5 + padding,
    }
    if needs_asr:
        assert manifest["transcription"]["cache_hit"]
        assert all(
            t.duration == 1800 and t.words[0].start == 600.75 for t in transcripts
        )
        (cached,) = (config.output_dir / ".cache" / "transcripts").glob("*.json")
        content = json.loads(cached.read_text())["transcript"]
        assert content["duration"] == 120.25 + 2 * padding
        assert content["words"][0]["start"] == 0.5 + padding
    else:
        assert manifest["transcription"] is None
    assert first.manifest_path != repeated.manifest_path
    changed = TimeRange(730.25, 850.5)
    run(
        replace(
            config, **{f"{'clip' if mode == 'custom' else 'search'}_range": changed}
        )
    )
    assert asr.calls == 2 * int(needs_asr)
    assert ai.calls == (4 if mode == "automatic" else 2)
    assert acquisition_ranges == [interval, interval, changed]


@pytest.mark.parametrize("long_enabled", [False, True])
def test_youtube_custom_cut_uses_acquired_duration_for_class_and_subtitles(
    long_enabled: bool, tmp_path: Path
) -> None:
    requested = TimeRange(100, 279)
    acquired = TimeRange(98, 281)
    media = replace(_media(), duration=183)
    source_path = tmp_path / "part.mp4"
    source_path.write_bytes(b"source")
    source = AcquiredSource(
        source_path,
        "partial-source",
        "youtube",
        "abc123",
        "Source title",
        "https://youtu.be/abc123",
        acquired_range=acquired,
        original_duration=600,
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    config = AppConfig(
        "https://youtu.be/abc123",
        tmp_path / "out",
        clip_range=requested,
        short_render="primary" if not long_enabled else False,
        long_render="primary" if long_enabled else False,
        short_subtitles_enabled=True,
        long_subtitles_enabled=False,
        render="primary",
        long_primary="horizontal",
    )

    def render(_source, _media, clip, _config, *, output, work):
        assert clip.proposal.clip_class == "long"
        assert (clip.proposal.start, clip.proposal.end) == (98, 281)
        output.parent.mkdir(parents=True)
        output.write_bytes(b"raw")
        return output, media, "16:9"

    def finish(raw, _media, transcript, clip, _config, *, output, work):
        assert transcript is None
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, output)
        return output, (), None

    def run():
        return run_pipeline(
            config,
            acquire=lambda *_args, **_kwargs: source,
            probe=lambda _: media,
            transcriber=asr,
            backend=ai,
            raw_renderer=render,
            final_renderer=finish,
        )

    if not long_enabled:
        with pytest.raises(ConfigurationError, match="interval is long"):
            run()
    else:
        result = run()
        metadata = json.loads(result.clip_paths[0].with_suffix(".json").read_text())
        assert metadata["class"] == "long"
        assert metadata["duration"] == 183
        assert metadata["render"]["subtitles_enabled"] is False
    assert asr.calls == ai.calls == 0


@pytest.mark.parametrize(
    ("download_range", "duration"),
    [
        (None, 1800),
        (TimeRange(0, 120), 120),
        (TimeRange(600, 720), 1800),
    ],
)
def test_partial_youtube_rejects_whole_or_mismatched_media_before_asr(
    download_range: TimeRange | None, duration: float, tmp_path: Path
) -> None:
    source = AcquiredSource(
        tmp_path / "part.mp4",
        "partial",
        "youtube",
        "abc123",
        "Title",
        "https://youtu.be/abc123",
        download_range,
        1800 if download_range is not None else None,
    )
    config = AppConfig(
        source.original_url or "", tmp_path / "out", clip_range=TimeRange(600, 720)
    )
    asr = FakeTranscriber()
    with pytest.raises(AcquisitionError, match="interval"):
        run_pipeline(
            config,
            acquire=lambda _source, _work, *, time_range=None: source,
            probe=lambda _: replace(_media(), duration=duration),
            transcriber=asr,
        )
    assert asr.calls == 0


@pytest.mark.parametrize("mode", ["custom", "automatic"])
@pytest.mark.parametrize("subtitles", [False, True])
def test_local_intervals_use_their_cache_or_a_compatible_complete_cache(
    mode: str, subtitles: bool, tmp_path: Path
) -> None:
    class Backend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            if "Find every" not in prompt:
                return super().complete(prompt, schema)
            self.calls += 1
            ids = re.findall(r"^(u\d+) \[", prompt, re.MULTILINE)
            return {
                "clips": [
                    {
                        "class": "short",
                        "start_id": ids[0],
                        "end_id": ids[-1] if len(ids) <= 3 else ids[1],
                        "title": "Scoped idea",
                        "rationale": "Complete point",
                    }
                ]
            }

    interval = TimeRange(90.25, 210.5)
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        clip_range=interval if mode == "custom" else None,
        search_range=interval if mode == "automatic" else None,
        subtitles_enabled=subtitles,
        render="primary",
    )
    asr, ai = FakeTranscriber(), Backend()
    extracted: list[TimeRange] = []

    def run(current: AppConfig):
        return _run(tmp_path, asr, ai, config=current, extraction_calls=extracted)

    first, repeated = run(config), run(config)
    needs_asr = subtitles or bool(config.llm_backend)
    assert asr.calls == int(needs_asr)
    assert extracted == [interval, interval]
    manifest = json.loads(repeated.manifest_path.read_text())
    assert manifest["source"]["acquired_range"] == {
        "start": interval.start,
        "end": interval.end,
    }
    if needs_asr:
        assert manifest["transcription"]["cache_hit"]
        assert manifest["transcription"]["source_range"] == {
            "start": 90.25,
            "end": 210.5,
        }
        (cached,) = (config.output_dir / ".cache" / "transcripts").glob("*.json")
        content = json.loads(cached.read_text(encoding="utf-8"))["transcript"]
        assert content["duration"] == 120.25
        assert content["segments"][0]["start"] == 0
    else:
        assert manifest["transcription"] is None
    for result in (first, repeated):
        metadata = json.loads(result.clip_paths[0].with_suffix(".json").read_text())
        assert (metadata["start"], metadata["end"]) == (90.25, 210.5)

    changed = TimeRange(240, 300)
    changed_config = replace(
        config,
        clip_range=changed if mode == "custom" else None,
        search_range=changed if mode == "automatic" else None,
    )
    run(changed_config)
    assert asr.calls == 2 * int(needs_asr)
    assert extracted == [interval, interval, changed]
    # A partial cache must never satisfy a request for the full source.
    full = replace(config, clip_range=None, search_range=None, full_video=True)
    full_result = run(full)
    assert asr.calls == 2 * int(needs_asr) + int(subtitles or bool(full.llm_backend))
    if subtitles or full.llm_backend:
        assert (
            json.loads(full_result.manifest_path.read_text())["transcription"][
                "source_range"
            ]
            is None
        )
        before = asr.calls
        reused = run(config)
        assert asr.calls == before
        assert extracted == [interval, interval, changed, interval]
        reused_manifest = json.loads(reused.manifest_path.read_text())
        assert reused_manifest["transcription"]["source_range"] == (
            {"start": interval.start, "end": interval.end} if mode == "custom" else None
        )
    run(replace(config, force_recompute=True))
    assert extracted == [interval, interval, changed] + (
        [interval] if subtitles or full.llm_backend else []
    ) + [interval]


@pytest.mark.parametrize("failure", ["malformed", "provider", "language"])
def test_local_range_recomputes_when_complete_cache_is_invalid(
    failure: str, tmp_path: Path
) -> None:
    asr = FakeTranscriber()
    _run(tmp_path, asr, FakeBackend(empty=True))
    output_dir = tmp_path / "out"
    (complete,) = (output_dir / ".cache" / "transcripts").glob("*.json")
    content = json.loads(complete.read_text(encoding="utf-8"))
    if failure == "malformed":
        complete.write_text("broken", encoding="utf-8")
    else:
        field, value = (
            ("provider_version", "4.9.0")
            if failure == "provider"
            else ("language_requested", "pt")
        )
        content["transcript"][field] = value
        complete.write_text(json.dumps(content), encoding="utf-8")
    interval = TimeRange(90.25, 120.5)
    config = AppConfig("source.mp4", output_dir, clip_range=interval, render="primary")
    extracted: list[TimeRange] = []
    result = _run(
        tmp_path, asr, FakeBackend(), config=config, extraction_calls=extracted
    )
    assert asr.calls == 2
    assert extracted == [interval]
    manifest = json.loads(result.manifest_path.read_text())
    assert not manifest["transcription"]["cache_hit"]
    assert manifest["transcription"]["source_range"] == {"start": 90.25, "end": 120.5}
    assert len(list(complete.parent.glob("*.json"))) == 2


def _run(
    tmp_path: Path,
    transcriber: FakeTranscriber,
    backend: FakeBackend,
    *,
    config: AppConfig | None = None,
    source_media: MediaInfo | None = None,
    extraction_calls: list[TimeRange] | None = None,
):
    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"source")
    current = config or AppConfig(
        source=str(source_file),
        output_dir=tmp_path / "out",
        llm_backend="codex",
        llm_model="test-model",
        subtitles_enabled=False,
    )
    source_info = source_media or _media()

    def acquire(
        _source: str, _workspace: Path, *, time_range: TimeRange | None = None
    ) -> AcquiredSource:
        return AcquiredSource(source_file, "sha256-v1:source")

    def raw_renderer(
        _source: AcquiredSource,
        _media: MediaInfo,
        clip,
        _config: AppConfig,
        *,
        output: Path,
        work: Path,
        should_cancel=None,
    ):
        if _source.acquired_range is None:
            assert _source.local_path == source_file
        else:
            assert _source.local_path != source_file
            assert _source.local_path.is_file()
            assert _source.acquired_range.start <= clip.proposal.start
            assert _source.acquired_range.end >= clip.proposal.end
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.parent.name == "direct-source":
            output.write_text(
                json.dumps([clip.proposal.start, clip.proposal.end]), encoding="utf-8"
            )
        else:
            output.write_bytes(b"raw")
        kind = clip.proposal.clip_class
        variant = _config.render_variant or _config.primary_for(kind, _media)
        width, height = _config.dimensions_for(kind, variant)
        return (
            output,
            _media_factory(width, height),
            _config.aspect_ratio_for(kind, variant),
        )

    def _media_factory(width: int, height: int) -> MediaInfo:
        return MediaInfo(360.0, width, height, width, height, 0, 1)

    def final_renderer(
        raw: Path,
        raw_media: MediaInfo,
        transcript: Transcript,
        clip,
        _config: AppConfig,
        *,
        output: Path,
        work: Path,
        should_cancel=None,
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, output)
        if not _config.subtitles_for(clip.proposal.clip_class):
            return output, (), None
        output.write_bytes(b"subtitled")
        subtitle_dir = output.parent / "subtitles"
        subtitle_dir.mkdir(exist_ok=True)
        sidecars = tuple(
            subtitle_dir / f"{output.stem}{suffix}"
            for suffix in (".transcript.json", ".srt", ".ass")
        )
        for path in sidecars:
            path.write_bytes(b"subtitle")
        return output, sidecars, _config.subtitle_template

    def range_extractor(source, media, interval, workspace):
        assert source.local_path == source_file
        if extraction_calls is not None:
            extraction_calls.append(interval)
        workspace.mkdir(parents=True)
        path = workspace / "source.range"
        path.write_text(json.dumps([interval.start, interval.end]), encoding="utf-8")
        return replace(
            source,
            local_path=path,
            acquired_range=interval,
            original_duration=media.duration,
            fingerprint=f"{source.fingerprint}:{float(interval.start)}-{float(interval.end)}:streamcopy",
        ), replace(media, duration=interval.end - interval.start)

    return run_pipeline(
        current,
        acquire=acquire,
        probe=lambda _: source_info,
        range_extractor=range_extractor,
        transcriber=transcriber,
        backend=backend,
        raw_renderer=raw_renderer,
        final_renderer=final_renderer,
    )


@pytest.mark.parametrize("subtitles", [False, True])
def test_output_groups_each_cut_and_labels_every_variant(
    tmp_path: Path, subtitles: bool
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        subtitles_enabled=subtitles,
    )
    result = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert root.name == result.run_id
    assert not (root / "clips").exists()
    assert not (root / "short").exists()
    assert not (root / "long").exists()
    assert re.fullmatch(r"\d{8}T\d{6}-source-[0-9a-f]{10}", result.run_id)
    assert manifest["source"]["title"] == "source"
    assert manifest["report"] == "report.md"
    report = result.report_path.read_text(encoding="utf-8")
    assert "Selected cuts: 2" in report
    assert "Score: 80.00/100" in report
    assert "Selection reason: Strong complete idea" in report
    assert "00:00:00.000" in report and "00:06:00.000" in report
    assert str(tmp_path) not in report
    assert "[Run manifest](manifest.json)" in report
    for reference in manifest["clips"]:
        primary = root / reference["video"]
        metadata = json.loads(primary.with_suffix(".json").read_text(encoding="utf-8"))
        directory = primary.parent
        class_directory = {"short": "shorts", "long": "longs"}[reference["class"]]
        assert directory.parent == root / class_directory
        assert directory.name.startswith(f"{metadata['rank']:03d}-")
        assert directory.name.endswith(f"-{reference['id']}")
        assert "-idea-" in directory.name
        assert f"## {metadata['rank']:03d}. {metadata['title']}" in report
        for variant in reference["variants"]:
            video = root / variant["video"]
            assert video.parent == directory
            assert video.name == f"{variant['variant']}.mp4"
            assert Path(variant["metadata"]).name == f"{variant['variant']}.json"
            assert f"[MP4]({variant['video']})" in report
            assert f"[JSON]({variant['metadata']})" in report
            details = json.loads(
                (root / variant["metadata"]).read_text(encoding="utf-8")
            )
            assert details["video"] == variant["video"]
            for sidecar in details["subtitle_files"]:
                path = root / sidecar
                assert path.parent == directory / "subtitles"
                assert path.name.startswith(video.stem + ".")
                assert path.is_file()
        primary_variant = reference["variants"][0]["variant"]
        assert primary.name == f"{primary_variant}.mp4"
        assert f"| {primary_variant} (primary) | [MP4]({reference['video']})" in report
        assert metadata["render"]["variant"] == primary_variant
        assert metadata["render"]["is_variant"] is False
    assert not (root / ".work").exists()


def test_output_preserves_titles_sanitizes_names_and_escapes_report_text(
    tmp_path: Path,
) -> None:
    title = "../../A decisão | [watch](https://example.com) <script>\n## Heading"
    reason = 'An explanation.\n# Fake heading <img src="remote"> &amp; [link](url)'

    class Backend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            response = super().complete(prompt, schema)
            assert isinstance(response, dict)
            if "Find every" in prompt:
                for proposal in response["clips"]:
                    proposal["title"] = title
            else:
                response["reason"] = reason
            return response

    result = _run(tmp_path, FakeTranscriber(), Backend())
    root = result.manifest_path.parent
    report = result.report_path.read_text(encoding="utf-8")
    assert "[watch](https://example.com)" not in report
    assert "<script>" not in report and '<img src="remote">' not in report
    assert "\n## Heading" not in report and "\n# Fake heading" not in report
    assert r"\[watch\]\(https://example.com\)" in report
    assert r"\&amp;" in report
    for video in result.clip_paths:
        assert video.parent.parent in (root / "shorts", root / "longs")
        assert re.fullmatch(r"[a-z0-9-]+", video.parent.name)
        assert "a-decisao" in video.parent.name
        metadata = json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
        assert metadata["title"] == title
        assert metadata["viral_potential"]["reason"] == reason


def test_report_collision_preserves_existing_file_and_prevents_completed_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    reports: list[Path] = []

    def raw_renderer(_source, media, _clip, _config, *, output, work):
        output.parent.mkdir(parents=True)
        output.write_bytes(b"raw")
        return output, media, "16:9"

    def final_renderer(raw, _media, _transcript, _clip, _config, *, output, work):
        output.parent.mkdir(parents=True)
        shutil.copyfile(raw, output)
        report = output.parents[2] / "report.md"
        report.write_text("Existing report\n", encoding="utf-8")
        reports.append(report)
        return output, (), None

    config = AppConfig(
        str(source),
        tmp_path / "out",
        full_video=True,
        render="primary",
        subtitles_enabled=False,
    )
    with pytest.raises(ArtifactError, match="Could not publish run report"):
        run_pipeline(
            config,
            acquire=lambda _source, _work, *, time_range=None: AcquiredSource(
                source, "sha256-v1:source"
            ),
            probe=lambda _: _media(),
            raw_renderer=raw_renderer,
            final_renderer=final_renderer,
        )
    (report,) = reports
    assert report.read_text(encoding="utf-8") == "Existing report\n"
    assert not report.with_name("manifest.json").exists()
    assert not (report.parent / ".work").exists()


def test_rerun_reuses_transcription_and_ai_but_publishes_fresh_clips(
    tmp_path: Path,
) -> None:
    first_asr = FakeTranscriber()
    first_ai = FakeBackend()
    first = _run(tmp_path, first_asr, first_ai)
    assert first_asr.calls == 1
    assert first_asr.settings == [("whisperx", "turbo")]
    assert first_ai.calls == 3
    assert len(first.clip_paths) == 2
    first_outputs = {path: path.read_bytes() for path in first.clip_paths}
    first_report = first.report_path.read_bytes()
    assert {"short", "long"} == {
        json.loads(path.with_suffix(".json").read_text())["class"]
        for path in first.clip_paths
    }

    second_asr = FakeTranscriber()
    second_ai = FakeBackend()
    second = _run(tmp_path, second_asr, second_ai)
    assert second_asr.calls == 0
    assert second_ai.calls == 0
    assert first.manifest_path != second.manifest_path
    assert first.report_path.read_bytes() == first_report
    assert second.report_path.is_file()
    assert all(path.read_bytes() == content for path, content in first_outputs.items())
    assert set(first.clip_paths).isdisjoint(second.clip_paths)
    manifest = json.loads(second.manifest_path.read_text())
    assert manifest["transcription"]["cache_hit"] is True
    assert manifest["transcription"]["backend"] == "whisperx"
    assert manifest["transcription"]["model"] == "turbo"
    assert manifest["analysis"]["ai_cache"] == {"hits": 3, "misses": 0}
    assert manifest["schema_version"] == 5
    assert manifest["analysis"]["editorially_eligible"] == 2
    assert manifest["analysis"]["selected"] == 2
    assert "minimum_score" not in manifest["analysis"]


@pytest.mark.parametrize("primary_variant", [None, *VARIANTS])
def test_pipeline_publishes_social_formats_per_cut_and_preserves_primary_version(
    primary_variant: str | None, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "test-model", subtitles_enabled=False
    )
    if primary_variant is not None:
        config = replace(
            config, short_primary=primary_variant, long_primary=primary_variant
        )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(tmp_path, asr, ai, config=config)
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text())
    assert asr.calls == 1 and ai.calls == 3
    assert len(result.clip_paths) == manifest["analysis"]["selected"] == 2
    expected_ratios = {"9:16", "16:9", "1:1"}
    for reference in manifest["clips"]:
        assert {
            item["aspect_ratio"] for item in reference["variants"]
        } == expected_ratios
        assert len(reference["variants"]) == 6
        primary = root / reference["video"]
        assert primary in result.clip_paths
        primary_metadata = json.loads((root / reference["metadata"]).read_text())
        expected_primary = config.aspect_ratio_for(
            reference["class"],
            primary_variant or config.primary_for(reference["class"], _media()),
        )
        assert primary_metadata["render"]["aspect_ratio"] == expected_primary
        for variant in reference["variants"]:
            video = root / variant["video"]
            assert video.is_file()
            metadata = json.loads((root / variant["metadata"]).read_text())
            assert metadata["video"] == variant["video"]
            assert metadata["id"] == reference["id"]
            assert metadata["start"] == primary_metadata["start"]
            assert metadata["end"] == primary_metadata["end"]
            assert metadata["viral_potential"] == primary_metadata["viral_potential"]
            render = metadata["render"]
            assert render["aspect_ratio"] == variant["aspect_ratio"]
            if variant["aspect_ratio"] == "9:16":
                assert (render["width"], render["height"]) == (1080, 1920)
            elif variant["aspect_ratio"] == "16:9":
                assert (render["width"], render["height"]) == (1920, 1080)
            elif variant["aspect_ratio"] == "1:1":
                assert (render["width"], render["height"]) == (1080, 1080)
            name = variant["variant"]
            assert render["variant"] == name
            assert render["layout"] == (
                "horizontal_center_blur"
                if name == "vertical-blur"
                else "vertical_center_blur"
                if name.endswith("-blur")
                else "center_crop"
            )
            assert render["subtitle_source_video"] is None
            assert metadata["subtitle_files"] == []
    assert len(list(root.rglob("*.mp4"))) == 12


@pytest.mark.parametrize("primary_variant", [None, *VARIANTS])
@pytest.mark.parametrize("subtitles", [False, True])
def test_disabled_variants_publish_only_primary_and_keep_caption_files(
    primary_variant: str | None, subtitles: bool, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        render="primary",
        subtitles_enabled=subtitles,
    )
    if primary_variant is not None:
        config = replace(
            config, short_primary=primary_variant, long_primary=primary_variant
        )
    result = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text())
    assert len(result.clip_paths) == len(list(root.rglob("*.mp4"))) == 2
    assert not (root / ".work").exists()
    for reference in manifest["clips"]:
        assert len(reference["variants"]) == 1
        metadata = json.loads((root / reference["metadata"]).read_text())
        assert (
            metadata["render"]["aspect_ratio"]
            == reference["variants"][0]["aspect_ratio"]
        )
        assert len(metadata["subtitle_files"]) == (3 if subtitles else 0)
        assert all(
            (root / path).is_file() and not path.startswith(".work/")
            for path in metadata["subtitle_files"]
        )
        if reference["class"] == "short" and primary_variant == "horizontal":
            assert metadata["render"]["layout"] == "center_crop"
            assert metadata["render"]["subtitle_source_video"] is None
            if subtitles:
                assert (root / reference["video"]).read_bytes() == b"subtitled"
                assert all(
                    Path(path).stem.startswith(Path(reference["video"]).stem)
                    for path in metadata["subtitle_files"]
                )


@pytest.mark.parametrize("primary_variant", ["horizontal", "vertical", "square"])
def test_square_source_supports_exactly_five_variants(
    primary_variant: str, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        subtitles_enabled=False,
        short_primary=primary_variant,
        long_primary=primary_variant,
    )
    result = _run(
        tmp_path,
        FakeTranscriber(),
        FakeBackend(),
        config=config,
        source_media=_media(720, 720),
    )
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text())
    expected_ratios = {"9:16", "16:9", "1:1"}
    for reference in manifest["clips"]:
        assert {
            item["aspect_ratio"] for item in reference["variants"]
        } == expected_ratios
        metadata = json.loads((root / reference["metadata"]).read_text())
        assert len(reference["variants"]) == 5
        assert metadata["render"]["variant"] == primary_variant


def test_square_primary_retains_other_variants(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        subtitles_enabled=False,
        short_primary="square",
        square_size=720,
    )
    result = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    manifest = json.loads(result.manifest_path.read_text())
    assert {item["class"]: len(item["variants"]) for item in manifest["clips"]} == {
        "short": 6,
        "long": 6,
    }
    short = next(item for item in manifest["clips"] if item["class"] == "short")
    metadata = json.loads((result.manifest_path.parent / short["metadata"]).read_text())
    assert (metadata["render"]["width"], metadata["render"]["height"]) == (720, 720)
    long = next(item for item in manifest["clips"] if item["class"] == "long")
    square = next(item for item in long["variants"] if item["aspect_ratio"] == "1:1")
    square_metadata = json.loads(
        (result.manifest_path.parent / square["metadata"]).read_text()
    )
    assert (
        square_metadata["render"]["width"],
        square_metadata["render"]["height"],
    ) == (720, 720)


def test_disabling_variants_reuses_caches_and_preserves_previous_outputs(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "test-model", subtitles_enabled=False
    )
    first = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    first_outputs = list(first.manifest_path.parent.rglob("*.mp4"))
    assert len(first_outputs) == 12
    transcriber, backend = FakeTranscriber(), FakeBackend()
    second = _run(
        tmp_path, transcriber, backend, config=replace(config, render="primary")
    )
    assert transcriber.calls == backend.calls == 0
    assert len(list(second.manifest_path.parent.rglob("*.mp4"))) == 2
    assert all(path.is_file() for path in first_outputs)


@pytest.mark.parametrize("clip_class", ["short", "long"])
@pytest.mark.parametrize(
    ("dimensions", "expected"),
    [
        ((1280, 720), set(VARIANTS)),
        ((900, 1200), {"vertical", "square", "horizontal-blur", "square-blur"}),
        (
            (720, 720),
            {"horizontal", "vertical", "square", "horizontal-blur", "vertical-blur"},
        ),
    ],
)
def test_each_duration_class_publishes_the_source_orientation_matrix(
    clip_class: str, dimensions: tuple[int, int], expected: set[str], tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        short_render=clip_class == "short",
        long_render=clip_class == "long",
    )
    asr = FakeTranscriber()
    result = _run(
        tmp_path, asr, FakeBackend(), config=config, source_media=_media(*dimensions)
    )
    assert asr.calls == 1
    manifest = json.loads(result.manifest_path.read_text())
    (cut,) = manifest["clips"]
    assert cut["class"] == clip_class
    assert {item["variant"] for item in cut["variants"]} == expected
    assert len(cut["variants"]) == len(expected)
    width, height = dimensions
    primary = (
        "horizontal" if width > height else "vertical" if width < height else "square"
    )
    assert cut["variants"][0]["variant"] == primary
    metadata = json.loads((result.manifest_path.parent / cut["metadata"]).read_text())
    assert metadata["render"]["variant"] == primary
    assert metadata["render"]["is_variant"] is False


@pytest.mark.parametrize("kind", ["short", "long"])
def test_named_render_reenables_judgment_and_publication_for_its_class(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = parse_run_config(
        [
            "source.mp4",
            "--output-dir",
            str(tmp_path / "out"),
            "--llm-backend",
            "codex",
            "--llm-model",
            "test-model",
            "--render",
            "false",
            "--render",
            f"{kind}:square=true",
            "--subtitles",
            "false",
        ]
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(tmp_path, asr, ai, config=config)
    manifest = json.loads(result.manifest_path.read_text())
    assert asr.calls == 1 and ai.calls == 2
    (cut,) = manifest["clips"]
    assert cut["class"] == kind
    assert [version["variant"] for version in cut["variants"]] == ["square"]


@pytest.mark.parametrize("clip_class", ["short", "long"])
def test_individual_blur_variant_and_subtitles_are_independent(
    clip_class: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    validated = []
    monkeypatch.setattr(
        "multicuts.pipeline.MultisubsAdapter.validate_subtitle_options",
        lambda _self, **settings: validated.append(settings),
    )
    options = SubtitleOptions(font_size="7%", position="top-center")
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        full_video=True,
        render="primary",
        short_subtitles_enabled=False,
        long_subtitles_enabled=False,
        output_options=(
            OutputOptions(clip_class, "horizontal", enabled=False),
            OutputOptions(clip_class, "vertical", enabled=False),
            OutputOptions(
                clip_class,
                "square-blur",
                enabled=True,
                subtitles_enabled=True,
                subtitle_template="amber-word",
                subtitle_options=options,
            ),
        ),
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(
        tmp_path,
        asr,
        ai,
        config=config,
        source_media=replace(
            _media(), duration=180 if clip_class == "short" else 180.01
        ),
    )
    assert asr.calls == 1 and ai.calls == 0
    assert validated == [
        {"template": "amber-word", "template_dir": None, "options": options}
    ]
    (video,) = result.clip_paths
    data = json.loads(video.with_suffix(".json").read_text())
    assert data["class"] == clip_class
    assert data["render"]["variant"] == "square-blur"
    assert data["render"]["subtitles_enabled"] is True
    assert data["render"]["subtitle_template"] == "amber-word"
    assert data["render"]["subtitle_overrides"] == options.metadata()
    assert len(list(video.parent.glob("*.mp4"))) == 1


@pytest.mark.parametrize("variant", ["horizontal", "vertical-blur"])
def test_unavailable_requested_variant_fails_before_asr(
    variant: str, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        full_video=True,
        output_options=(OutputOptions("short", variant, enabled=True),),
    )
    asr = FakeTranscriber()
    with pytest.raises(ConfigurationError, match="unavailable"):
        _run(
            tmp_path,
            asr,
            FakeBackend(),
            config=config,
            source_media=replace(_media(720, 1280), duration=180),
        )
    assert asr.calls == 0


def test_disabling_all_variants_fails_before_asr(tmp_path: Path) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        full_video=True,
        output_options=tuple(
            OutputOptions("long", name, enabled=False) for name in VARIANTS
        ),
    )
    asr = FakeTranscriber()
    with pytest.raises(ConfigurationError, match="at least one long output"):
        _run(tmp_path, asr, FakeBackend(), config=config)
    assert asr.calls == 0


def test_named_caption_switch_skips_asr_for_the_only_published_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = parse_run_config(
        [
            "source.mp4",
            "--output-dir",
            str(tmp_path / "out"),
            "--clip-full",
            "--render",
            "primary",
            "--render",
            "short:horizontal=false",
            "--render",
            "short:square-blur=true",
            "--subtitles",
            "short:square-blur=false",
        ]
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(
        tmp_path, asr, ai, config=config, source_media=replace(_media(), duration=180)
    )
    assert asr.calls == ai.calls == 0
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["transcription"] is None
    (clip,) = manifest["clips"]
    assert [item["variant"] for item in clip["variants"]] == ["square-blur"]


def test_each_variant_has_its_own_final_geometry_caption_sidecars(
    tmp_path: Path,
) -> None:
    config = AppConfig("source.mp4", tmp_path / "out", "codex", "test-model")
    result = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text())
    for reference in manifest["clips"]:
        seen: set[str] = set()
        assert {item["variant"] for item in reference["variants"]} == set(VARIANTS)
        for item in reference["variants"]:
            metadata = json.loads((root / item["metadata"]).read_text())
            assert metadata["render"]["subtitles_enabled"] is True
            assert metadata["render"]["subtitle_template"] == "yellow-pop"
            assert metadata["render"]["subtitle_source_video"] is None
            assert len(metadata["subtitle_files"]) == 3
            assert seen.isdisjoint(metadata["subtitle_files"])
            seen.update(metadata["subtitle_files"])
            assert all((root / path).is_file() for path in metadata["subtitle_files"])


@pytest.mark.parametrize("variants", [False, True])
@pytest.mark.parametrize(
    ("general", "short", "long", "expected_short", "expected_long"),
    [
        (True, None, None, True, True),
        (False, None, None, False, False),
        (True, True, False, True, False),
        (True, False, True, False, True),
        (False, True, None, True, False),
        (False, None, True, False, True),
    ],
)
def test_class_subtitle_controls_apply_to_every_version(
    general: bool,
    short: bool | None,
    long: bool | None,
    expected_short: bool,
    expected_long: bool,
    variants: bool,
    tmp_path: Path,
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        subtitles_enabled=general,
        short_subtitles_enabled=short,
        long_subtitles_enabled=long,
        render=True if variants else "primary",
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(tmp_path, asr, ai, config=config)
    assert asr.calls == 1 and ai.calls == 3
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text())
    for reference in manifest["clips"]:
        expected = expected_short if reference["class"] == "short" else expected_long
        assert len(reference["variants"]) == (6 if variants else 1)
        for variant in reference["variants"]:
            metadata = json.loads((root / variant["metadata"]).read_text())
            assert metadata["render"]["subtitles_enabled"] is expected
            assert metadata["render"]["subtitle_provider"] == (
                "multisubs" if expected else None
            )
            assert metadata["render"]["subtitle_template"] == (
                "yellow-pop" if expected else None
            )
            assert len(metadata["subtitle_files"]) == (3 if expected else 0)
            assert (root / variant["video"]).read_bytes() == (
                b"subtitled" if expected else b"raw"
            )
            assert all((root / path).is_file() for path in metadata["subtitle_files"])
            if not expected:
                assert metadata["render"]["subtitle_source_video"] is None


@pytest.mark.parametrize("enabled", ["short", "long"])
def test_disabled_clip_class_is_not_reviewed_or_published(
    enabled: str, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        subtitles_enabled=False,
        short_render=enabled == "short",
        long_render=enabled == "long",
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(tmp_path, asr, ai, config=config)
    manifest = json.loads(result.manifest_path.read_text())
    assert asr.calls == 1 and ai.calls == 2
    assert manifest["analysis"]["proposed"] == manifest["analysis"]["selected"] == 1
    assert {clip["class"] for clip in manifest["clips"]} == {enabled}
    assert len(result.clip_paths) == 1
    assert len(list(result.manifest_path.parent.rglob("*.mp4"))) == 6


@pytest.mark.parametrize("short_variants", [False, True])
@pytest.mark.parametrize("long_variants", [False, True])
def test_each_class_controls_its_variants(
    short_variants: bool, long_variants: bool, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        subtitles_enabled=False,
        render="primary",
        short_render=True if short_variants else "primary",
        long_render=True if long_variants else "primary",
    )
    result = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    manifest = json.loads(result.manifest_path.read_text())
    counts = {clip["class"]: len(clip["variants"]) for clip in manifest["clips"]}
    assert counts == {
        "short": 6 if short_variants else 1,
        "long": 6 if long_variants else 1,
    }


@pytest.mark.parametrize("primary_variant", ["vertical", "horizontal", "square"])
@pytest.mark.parametrize("primary_subtitles", [False, True])
@pytest.mark.parametrize("variant_subtitles", [None, False, True])
def test_primary_and_variant_subtitles_are_independent_and_persisted(
    primary_variant: str,
    primary_subtitles: bool,
    variant_subtitles: bool | None,
    tmp_path: Path,
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        short_primary=primary_variant,
        long_primary=primary_variant,
        short_subtitles_enabled=primary_subtitles,
        long_subtitles_enabled=primary_subtitles,
        output_options=tuple(
            OutputOptions(clip_class, name, subtitles_enabled=variant_subtitles)
            for clip_class in ("short", "long")
            for name in VARIANTS
            if name != primary_variant
        ),
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(tmp_path, asr, ai, config=config)
    assert asr.calls == 1 and ai.calls == 3
    root = result.manifest_path.parent
    assert not (root / ".work").exists()
    manifest = json.loads(result.manifest_path.read_text())
    for clip in manifest["clips"]:
        for version in clip["variants"]:
            metadata = json.loads((root / version["metadata"]).read_text())
            is_variant = version["video"] != clip["video"]
            expected = (
                variant_subtitles
                if is_variant and variant_subtitles is not None
                else primary_subtitles
            )
            assert metadata["render"]["is_variant"] is is_variant
            assert metadata["render"]["subtitles_enabled"] is expected
            assert (root / version["video"]).read_bytes() == (
                b"subtitled" if expected else b"raw"
            )
            assert len(metadata["subtitle_files"]) == (3 if expected else 0)
            assert all((root / path).is_file() for path in metadata["subtitle_files"])
            if not expected:
                assert metadata["render"]["subtitle_provider"] is None
                assert metadata["render"]["subtitle_template"] is None
                assert metadata["render"]["subtitle_source_video"] is None
            if (
                clip["class"] == "short"
                and version["aspect_ratio"] == "16:9"
                and variant_subtitles is not None
                and primary_subtitles != variant_subtitles
                and primary_variant in ("vertical", "horizontal")
            ):
                assert metadata["render"]["subtitle_source_video"] is None


@pytest.mark.parametrize("primary_subtitles", [False, True])
@pytest.mark.parametrize("unused_variant_subtitles", [False, True])
def test_horizontal_only_short_uses_primary_subtitles(
    primary_subtitles: bool, unused_variant_subtitles: bool, tmp_path: Path
) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        short_render="primary",
        long_render=False,
        short_primary="horizontal",
        short_subtitles_enabled=primary_subtitles,
        output_options=(
            OutputOptions(
                "short", "vertical", subtitles_enabled=unused_variant_subtitles
            ),
        ),
    )
    result = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    (video,) = result.clip_paths
    metadata = json.loads(video.with_suffix(".json").read_text())
    assert metadata["render"]["is_variant"] is False
    assert metadata["render"]["subtitles_enabled"] is primary_subtitles
    assert video.read_bytes() == (b"subtitled" if primary_subtitles else b"raw")
    assert len(list(video.parent.glob("*.mp4"))) == 1
    assert all(
        (result.manifest_path.parent / path).is_file()
        for path in metadata["subtitle_files"]
    )


def test_reenabling_class_reuses_proposals_and_transcription(tmp_path: Path) -> None:
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        long_render=False,
        subtitles_enabled=False,
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    asr, ai = FakeTranscriber(), FakeBackend()
    second = _run(
        tmp_path,
        asr,
        ai,
        config=replace(
            config,
            long_render="primary",
            output_options=(
                OutputOptions("short", "horizontal-blur", subtitles_enabled=True),
            ),
        ),
    )
    assert asr.calls == 0 and ai.calls == 1
    assert len(second.clip_paths) == 2
    asr, ai = FakeTranscriber(), FakeBackend()
    _run(
        tmp_path,
        asr,
        ai,
        config=replace(config, short_render=False, long_render=True),
    )
    assert asr.calls == ai.calls == 0


def test_changing_class_subtitles_reuses_transcription_and_ai(tmp_path: Path) -> None:
    config = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "test-model", subtitles_enabled=False
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(
        tmp_path, asr, ai, config=replace(config, short_subtitles_enabled=True)
    )
    assert asr.calls == ai.calls == 0
    for video in result.clip_paths:
        metadata = json.loads(video.with_suffix(".json").read_text())
        assert metadata["render"]["subtitles_enabled"] is (metadata["class"] == "short")


@pytest.mark.parametrize("subtitles", [False, True])
@pytest.mark.parametrize("jobs", [1, 3])
def test_pipeline_reports_stages_selection_rendering_and_cache_reuse(
    subtitles: bool, jobs: int, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="multicuts.pipeline")
    config = AppConfig(
        source=str(tmp_path / "source.mp4"),
        output_dir=tmp_path / "out",
        llm_backend="codex",
        llm_model="test-model",
        subtitles_enabled=subtitles,
        render_jobs=jobs,
    )
    first = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    messages = caplog.messages
    for stage in range(1, 7):
        assert any(message.startswith(f"[{stage}/6]") for message in messages)
    assert (
        "[3/6] Finding candidates in 1 transcript blocks "
        "(backend=codex, model=test-model, effort=auto)" in messages
    )
    assert (
        "Transcription cache miss; running ASR "
        "(backend=whisperx, model=turbo, language=auto)" in messages
    )
    assert "Found 2 unique candidates: 1 short, 1 long" in messages
    assert "Analyzing transcript block 1/1" in messages
    assert any("Reviewing candidate 2/2" in message for message in messages)
    first_result = next(
        index
        for index, message in enumerate(messages)
        if message.startswith("Candidate 1/2: approved,")
    )
    next_review = next(
        index
        for index, message in enumerate(messages)
        if message.startswith("Reviewing candidate 2/2")
    )
    second_result = next(
        index
        for index, message in enumerate(messages)
        if message.startswith("Candidate 2/2: approved,")
    )
    selection = next(
        index
        for index, message in enumerate(messages)
        if message.startswith("[5/6] Selection:")
    )
    assert first_result < next_review < second_result < selection
    assert any("2 approved, 0 rejected, 2 selected" in message for message in messages)
    assert any("cache: 0 hits, 3 misses" in message for message in messages)
    assert any("Rendering clip 2/2: long" in message for message in messages)
    assert any("Clip 2/2 saved:" in message for message in messages)
    manifest = json.loads(first.manifest_path.read_text())
    for rank, clip in enumerate(manifest["clips"], start=1):
        cut_saved = next(
            index
            for index, message in enumerate(messages)
            if message.startswith(f"Clip {rank}/2 saved:")
        )
        for variant in clip["variants"]:
            prefix = (
                f"Clip {rank}/2 version {variant['variant']} saved: {variant['video']} "
            )
            matching = [
                index
                for index, message in enumerate(messages)
                if message.startswith(prefix)
            ]
            assert len(matching) == 1
            assert matching[0] < cut_saved
            assert re.fullmatch(
                re.escape(prefix) + r"\(\d+\.\ds\)", messages[matching[0]]
            )
    assert any(str(first.manifest_path) in message for message in messages)
    assert (
        any("Adding subtitles to clip" in message for message in messages) is subtitles
    )
    assert not any("Point 0." in message for message in messages)

    caplog.clear()
    asr, ai = FakeTranscriber(), FakeBackend()
    _run(tmp_path, asr, ai, config=config)
    assert asr.calls == ai.calls == 0
    assert (
        "Transcription cache hit; reusing the source transcript "
        "(backend=whisperx, model=turbo)" in caplog.messages
    )
    assert any("cache: 3 hits, 0 misses" in message for message in caplog.messages)
    assert not any("running ASR" in message for message in caplog.messages)


def test_pipeline_explains_zero_selection_without_rendering_progress(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="multicuts.pipeline")
    _run(tmp_path, FakeTranscriber(), FakeBackend(empty=True))
    assert "[6/6] No clips selected; rendering skipped" in caplog.messages
    assert any(
        "0 approved, 0 rejected, 0 selected" in message for message in caplog.messages
    )
    assert not any("Rendering clip" in message for message in caplog.messages)


def test_force_recompute_bypasses_both_expensive_caches(tmp_path: Path) -> None:
    base = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "test-model", subtitles_enabled=False
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=base)
    asr = FakeTranscriber()
    ai = FakeBackend()
    _run(tmp_path, asr, ai, config=replace(base, force_recompute=True))
    assert asr.calls == 1
    assert ai.calls == 3


def test_editorial_context_reaches_both_prompts_and_invalidates_only_ai_cache(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class ContextBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.prompts: list[str] = []

        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            self.prompts.append(prompt)
            return super().complete(prompt, schema)

    caplog.set_level(logging.INFO, logger="multicuts.pipeline")
    base = AppConfig(
        source=str(tmp_path / "source.mp4"),
        output_dir=tmp_path / "out",
        llm_backend="codex",
        llm_model="test-model",
        subtitles_enabled=False,
    )
    initial_ai = ContextBackend()
    initial = _run(tmp_path, FakeTranscriber(), initial_ai, config=base)
    assert initial_ai.calls == 3
    assert all("Editorial context:" not in prompt for prompt in initial_ai.prompts)
    assert (
        json.loads(initial.manifest_path.read_text(encoding="utf-8"))["analysis"][
            "editorial_context"
        ]
        is None
    )

    context = 'Entrevista sobre educação.\nO convidado é conhecido como "professor".'
    contextual = replace(base, editorial_context=context)
    asr, ai = FakeTranscriber(), ContextBackend()
    result = _run(tmp_path, asr, ai, config=contextual)
    assert asr.calls == 0
    assert ai.calls == len(ai.prompts) == 3
    assert len(result.clip_paths) == 2
    for prompt in ai.prompts:
        assert json.dumps(context, ensure_ascii=False) in prompt
        assert "mandatory topic or keyword filter" in prompt
        assert "Context is background, not transcript evidence" in prompt
    assert "identify the most relevant complete ideas" in ai.prompts[0]
    for prompt in ai.prompts[1:]:
        assert "Context alone neither approves nor rejects a candidate" in prompt
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["analysis"]["editorial_context"] == context
    assert manifest["analysis"]["ai_cache"] == {"hits": 0, "misses": 3}
    for video in result.clip_paths:
        assert (
            json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))[
                "viral_potential"
            ]["editorial_context"]
            == context
        )
    assert any("Video context enabled" in message for message in caplog.messages)
    assert "Entrevista sobre educação" not in caplog.text

    repeated_asr, repeated_ai = FakeTranscriber(), ContextBackend()
    repeated = _run(
        tmp_path,
        repeated_asr,
        repeated_ai,
        config=replace(base, editorial_context="  " + context + "  "),
    )
    assert repeated_asr.calls == repeated_ai.calls == 0
    assert json.loads(repeated.manifest_path.read_text(encoding="utf-8"))["analysis"][
        "ai_cache"
    ] == {
        "hits": 3,
        "misses": 0,
    }

    changed_asr, changed_ai = FakeTranscriber(), ContextBackend()
    _run(
        tmp_path,
        changed_asr,
        changed_ai,
        config=replace(base, editorial_context="Interview about running a business"),
    )
    assert changed_asr.calls == 0
    assert changed_ai.calls == 3
    restored_asr, restored_ai = FakeTranscriber(), ContextBackend()
    _run(
        tmp_path, restored_asr, restored_ai, config=replace(base, editorial_context="")
    )
    assert restored_asr.calls == restored_ai.calls == 0


def test_model_change_reuses_asr_but_recomputes_ai(tmp_path: Path) -> None:
    base = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "model-a", subtitles_enabled=False
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=base)
    asr = FakeTranscriber()
    ai = FakeBackend()
    _run(tmp_path, asr, ai, config=replace(base, llm_model="model-b"))
    assert asr.calls == 0
    assert ai.calls == 3


def test_effort_change_reuses_asr_but_recomputes_ai(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="multicuts.pipeline")
    base = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "model-a", subtitles_enabled=False
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=base)
    config = replace(base, llm_effort="high")
    asr = FakeTranscriber()
    ai = FakeBackend()
    result = _run(tmp_path, asr, ai, config=config)
    assert (
        "[3/6] Finding candidates in 1 transcript blocks "
        "(backend=codex, model=model-a, effort=high)" in caplog.messages
    )
    assert asr.calls == 0
    assert ai.calls == 3
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["analysis"]["effort"] == "high"
    clip = json.loads(result.clip_paths[0].with_suffix(".json").read_text())
    assert clip["viral_potential"]["effort"] == "high"

    repeated_asr = FakeTranscriber()
    repeated_ai = FakeBackend()
    _run(tmp_path, repeated_asr, repeated_ai, config=config)
    assert repeated_asr.calls == 0
    assert repeated_ai.calls == 0


def test_geometry_change_reuses_both_expensive_caches(tmp_path: Path) -> None:
    base = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "model-a", subtitles_enabled=False
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=base)
    asr = FakeTranscriber()
    ai = FakeBackend()
    _run(
        tmp_path,
        asr,
        ai,
        config=replace(base, vertical_width=720, vertical_height=1280),
    )
    assert asr.calls == 0
    assert ai.calls == 0


def test_subtitle_changes_reuse_asr_and_ai_and_preserve_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    validated = []
    monkeypatch.setattr(
        "multicuts.pipeline.MultisubsAdapter.validate_subtitle_options",
        lambda _self, **settings: validated.append(settings),
    )
    config = AppConfig("source.mp4", tmp_path / "out", "codex", "model-a")
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    options = SubtitleOptions(
        position="bottom-center",
        margin_bottom="8%",
        font_size="4.5%",
        fonts_dir=tmp_path / "private-fonts",
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(
        tmp_path,
        asr,
        ai,
        config=replace(
            config, subtitle_template="amber-word", subtitle_options=options
        ),
    )
    assert asr.calls == ai.calls == 0
    assert validated == [
        {"template": "amber-word", "template_dir": None, "options": options}
    ]
    manifest = json.loads(result.manifest_path.read_text())
    for clip in manifest["clips"]:
        for version in clip["variants"]:
            data = json.loads(
                (result.manifest_path.parent / version["metadata"]).read_text()
            )
            assert data["render"]["subtitle_overrides"] == options.metadata()
            assert "private-fonts" not in json.dumps(data)


def test_invalid_subtitle_settings_fail_before_acquisition(
    tmp_path, monkeypatch
) -> None:
    import sys
    from types import ModuleType

    provider = ModuleType("multisubs")

    def reject(**_settings):
        raise ValueError("inactive bottom margin")

    provider.__dict__["build_subtitle_config"] = reject
    provider.__dict__["MultisubsError"] = ValueError
    monkeypatch.setitem(sys.modules, "multisubs", provider)
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        full_video=True,
        subtitle_options=SubtitleOptions(position="top-center", margin_bottom="0%"),
    )
    with pytest.raises(ConfigurationError, match="inactive bottom margin"):
        run_pipeline(
            config, acquire=lambda *_args, **_kwargs: pytest.fail("acquisition started")
        )
    assert not config.output_dir.exists()


@pytest.mark.parametrize(
    ("backend", "model"), [("faster-whisper", "turbo"), ("whisperx", "medium")]
)
def test_asr_settings_have_separate_reusable_transcript_caches(
    tmp_path: Path, backend: str, model: str
) -> None:
    base = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "test-model", subtitles_enabled=False
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=base)
    changed = replace(base, asr_backend=backend, transcription_model=model)
    asr = FakeTranscriber()
    result = _run(tmp_path, asr, FakeBackend(), config=changed)
    assert asr.calls == 1
    assert asr.settings == [(backend, model)]
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["transcription"]["backend"] == backend
    assert manifest["transcription"]["model"] == model
    assert manifest["transcription"]["cache_hit"] is False

    for config in (changed, base):
        repeated_asr = FakeTranscriber()
        repeated = _run(tmp_path, repeated_asr, FakeBackend(), config=config)
        assert repeated_asr.calls == 0
        assert (
            json.loads(repeated.manifest_path.read_text())["transcription"]["cache_hit"]
            is True
        )


def test_language_change_invalidates_transcript_cache(tmp_path: Path) -> None:
    base = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "test-model", subtitles_enabled=False
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=base)
    asr = FakeTranscriber()
    ai = FakeBackend()
    result = _run(tmp_path, asr, ai, config=replace(base, language="pt"))
    assert asr.calls == 1
    assert ai.calls == 3
    assert (
        json.loads(result.manifest_path.read_text())["transcription"][
            "language_requested"
        ]
        == "pt"
    )


@pytest.mark.parametrize(
    "legacy_digest",
    [
        "a07e72a63150a17781b04e1e2da11a19a129bf7701252a245c37a6be86560c24",
        "b7df89fcaf19b368f32399708a47ed1f15d77524ead267dab48a68f516c8301f",
    ],
)
def test_legacy_subtitle_grouped_cache_is_not_reused_for_raw_speech(
    tmp_path: Path,
    legacy_digest: str,
) -> None:
    asr = FakeTranscriber()
    _run(tmp_path, asr, FakeBackend(empty=True))
    cache_dir = tmp_path / "out" / ".cache" / "transcripts"
    (current,) = cache_dir.glob("*.json")
    payload = json.loads(current.read_text())
    # Golden identities from transcript stages 2 and 3 for this configuration.
    legacy = cache_dir / f"{legacy_digest}.json"
    payload["key"] = f"sha256-v1:{legacy_digest}"
    current.rename(legacy)
    legacy.write_text(json.dumps(payload), encoding="utf-8")
    result = _run(tmp_path, asr, FakeBackend(empty=True))
    assert asr.calls == 2
    assert not json.loads(result.manifest_path.read_text())["transcription"][
        "cache_hit"
    ]
    assert legacy.is_file()
    assert current.is_file()


def test_malformed_transcript_cache_is_recomputed(tmp_path: Path) -> None:
    _run(tmp_path, FakeTranscriber(), FakeBackend())
    cache_path = next((tmp_path / "out" / ".cache" / "transcripts").glob("*.json"))
    cache_path.write_text('{"schema_version":1,"key":"wrong"}', encoding="utf-8")
    asr = FakeTranscriber()
    ai = FakeBackend()
    _run(tmp_path, asr, ai)
    assert asr.calls == 1
    assert ai.calls == 0


def test_malformed_ai_cache_is_recomputed(tmp_path: Path) -> None:
    _run(tmp_path, FakeTranscriber(), FakeBackend())
    cache_path = next((tmp_path / "out" / ".cache" / "ai").glob("*.json"))
    cache_path.write_text('{"schema_version":1,"key":"wrong"}', encoding="utf-8")
    asr = FakeTranscriber()
    ai = FakeBackend()
    _run(tmp_path, asr, ai)
    assert asr.calls == 0
    assert ai.calls == 1


def test_zero_approved_clips_is_a_valid_completed_analysis(tmp_path: Path) -> None:
    result = _run(tmp_path, FakeTranscriber(), FakeBackend(empty=True))
    assert result.clip_paths == ()
    assert json.loads(result.manifest_path.read_text())["outcome"] == "zero_selection"
    report = result.report_path.read_text(encoding="utf-8")
    assert "Selected cuts: 0" in report
    assert "No cuts were selected." in report
    assert "[MP4]" not in report


@pytest.mark.parametrize("reject_long", [False, True])
@pytest.mark.parametrize("context", [None, "A host reviews Pokémon games."])
def test_pipeline_preserves_editorial_rejections_after_boundary_review_and_cache(
    tmp_path: Path,
    reject_long: bool,
    context: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="multicuts.pipeline")

    class RejectingBackend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            response = super().complete(prompt, schema)
            if "Original boundary IDs: u0 through u1" in prompt:
                assert isinstance(response, dict)
                return {
                    **response,
                    "start_id": "u1",
                    "approved": False,
                    "reason": "The revised opening cannot repair the missing close",
                }
            if reject_long and "Original boundary IDs: u0 through u5" in prompt:
                assert isinstance(response, dict)
                return {
                    **response,
                    "approved": False,
                    "reason": "The discussion lacks a complete central idea",
                }
            return response

    config = AppConfig(
        source=str(tmp_path / "source.mp4"),
        output_dir=tmp_path / "out",
        llm_backend="codex",
        llm_model="test-model",
        subtitles_enabled=False,
        editorial_context=context,
    )
    first_ai = RejectingBackend()
    first = _run(tmp_path, FakeTranscriber(), first_ai, config=config)
    assert first_ai.calls == 3
    expected_results = [
        "Candidate 1/2: rejected",
        f"Candidate 2/2: {'rejected' if reject_long else 'approved'}",
    ]
    assert [
        message.split(",", 1)[0]
        for message in caplog.messages
        if message.startswith("Candidate ")
    ] == expected_results

    caplog.clear()
    second_asr = FakeTranscriber()
    second_ai = RejectingBackend()
    second = _run(tmp_path, second_asr, second_ai, config=config)
    assert second_asr.calls == 0
    assert second_ai.calls == 0
    assert [
        message.split(",", 1)[0]
        for message in caplog.messages
        if message.startswith("Candidate ")
    ] == expected_results
    assert json.loads(second.manifest_path.read_text())["analysis"]["ai_cache"] == {
        "hits": 3,
        "misses": 0,
    }

    expected_count = 0 if reject_long else 1
    for result in (first, second):
        manifest = json.loads(result.manifest_path.read_text())
        assert manifest["analysis"]["proposed"] == 2
        assert manifest["analysis"]["boundary_adjusted"] == 1
        assert manifest["analysis"]["editorially_eligible"] == expected_count
        assert manifest["analysis"]["selected"] == expected_count
        assert manifest["outcome"] == ("zero_selection" if reject_long else "completed")
        assert len(result.clip_paths) == expected_count
        for path in result.clip_paths:
            metadata = json.loads(path.with_suffix(".json").read_text())
            assert metadata["class"] == "long"
            assert metadata["viral_potential"]["approved"] is True


def test_invalid_ai_response_fails_explicitly_and_is_not_cached(tmp_path: Path) -> None:
    invalid = FakeBackend(invalid=True)
    with pytest.raises(ScoringError):
        _run(tmp_path, FakeTranscriber(), invalid)
    valid = FakeBackend()
    _run(tmp_path, FakeTranscriber(), valid)
    assert valid.calls == 3


@pytest.mark.parametrize("context", [None, "A host reviews Pokémon games."])
def test_social_title_guidance_and_titles_survive_judgment_and_cache(
    tmp_path: Path, context: str | None
) -> None:
    titles = {
        "short": "Estudar mais não é aprender mais",
        "long": "Por que você estuda tanto e aprende tão pouco?",
    }

    class TitleBackend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            response = super().complete(prompt, schema)
            if "Find every" in prompt:
                properties = schema["properties"]
                assert isinstance(properties, dict)
                clips = properties["clips"]
                assert isinstance(clips, dict)
                title = clips["items"]["properties"]["title"]
                assert title["type"] == "string"
                description = title["description"]
                assert isinstance(description, str)
                assert description in prompt
                for guidance in (
                    "attention-grabbing social-media title",
                    "same language as the clip's transcript",
                    "simple, everyday words",
                    "casual, conversational tone",
                    "telling a friend",
                    "direct, active verbs",
                    "Avoid formal, academic, or corporate wording",
                    "complex vocabulary",
                    "do not copy the speaker's formal register",
                    "Do not force slang",
                    "40–80 characters",
                    "never more than 120 characters",
                    "Shorter titles are welcome",
                    "never add filler",
                    "Put the hook in the first words",
                    "specific subject",
                    "question that the clip answers",
                    "What happens when you sleep too little?",
                    "Buying on impulse is costing you money",
                    "style examples only",
                    "do not reuse their topics or claims",
                    "within the chosen start_id and end_id",
                    "editorial context cannot supply title facts",
                    "without misleading clickbait",
                    "Avoid hashtags, emojis, ALL CAPS",
                ):
                    assert guidance in description
                assert isinstance(response, dict)
                for proposal in response["clips"]:
                    proposal["title"] = titles[proposal["class"]]
            else:
                assert all(title not in prompt for title in titles.values())
            return response

    config = AppConfig(
        source=str(tmp_path / "source.mp4"),
        output_dir=tmp_path / "out",
        llm_backend="codex",
        llm_model="test-model",
        subtitles_enabled=False,
        editorial_context=context,
    )
    first_asr, first_ai = FakeTranscriber(), TitleBackend()
    first = _run(tmp_path, first_asr, first_ai, config=config)
    assert first_asr.calls == 1
    assert first_ai.calls == 3
    repeated_asr, repeated_ai = FakeTranscriber(), TitleBackend()
    repeated = _run(tmp_path, repeated_asr, repeated_ai, config=config)
    assert repeated_asr.calls == repeated_ai.calls == 0
    for result in (first, repeated):
        assert len(result.clip_paths) == 2
        for path in result.clip_paths:
            metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            assert metadata["title"] == titles[metadata["class"]]


@pytest.mark.parametrize("previous_version", ["semantic-clips-v8", "semantic-clips-v9"])
def test_title_prompt_version_change_recomputes_ai_and_reuses_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, previous_version: str
) -> None:
    with monkeypatch.context() as previous:
        previous.setattr("multicuts.cache.PROMPT_VERSION", previous_version)
        previous.setattr("multicuts.pipeline.PROMPT_VERSION", previous_version)
        initial = _run(tmp_path, FakeTranscriber(), FakeBackend())
    original_metadata = {
        path: path.with_suffix(".json").read_bytes() for path in initial.clip_paths
    }

    asr, ai = FakeTranscriber(), FakeBackend()
    current = _run(tmp_path, asr, ai)
    assert asr.calls == 0
    assert ai.calls == 3
    manifest = json.loads(current.manifest_path.read_text(encoding="utf-8"))
    assert manifest["analysis"]["prompt_version"] == "semantic-clips-v10"
    assert manifest["analysis"]["score_version"] == "viral-potential-v3"
    assert manifest["analysis"]["ai_cache"] == {"hits": 0, "misses": 3}
    for path, metadata in original_metadata.items():
        assert path.with_suffix(".json").read_bytes() == metadata


@pytest.mark.parametrize("context", [None, "A host reviews Pokémon games."])
def test_score_reason_guidance_reaches_prompt_and_schema(
    tmp_path: Path, context: str | None
) -> None:
    class CheckingBackend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            if "Original boundary IDs:" in prompt:
                properties = schema["properties"]
                assert isinstance(properties, dict)
                reason = properties["reason"]
                assert isinstance(reason, dict)
                assert reason["type"] == "string"
                description = reason["description"]
                assert isinstance(description, str)
                assert "non-empty text" in description
                assert "Prefer a concise explanation" in description
                assert "include more detail when needed" in description
                assert "Avoid whitespace-only text" in description
                assert description in prompt
            return super().complete(prompt, schema)

    config = AppConfig(
        source=str(tmp_path / "source.mp4"),
        output_dir=tmp_path / "out",
        llm_backend="codex",
        llm_model="test-model",
        subtitles_enabled=False,
        editorial_context=context,
    )
    ai = CheckingBackend()
    result = _run(tmp_path, FakeTranscriber(), ai, config=config)
    assert ai.calls == 3
    assert len(result.clip_paths) == 2


@pytest.mark.parametrize(
    ("reason", "error"),
    [
        ("  Concise editorial explanation.  ", None),
        ("", "text is empty"),
        (" \t\n", "text is empty"),
        (None, "expected text, received NoneType"),
        (["provider-secret"], "expected text, received list"),
    ],
)
def test_score_reason_validation_and_cache_recovery(
    tmp_path: Path, reason: object, error: str | None
) -> None:
    class ReasonBackend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            response = super().complete(prompt, schema)
            if "Original boundary IDs:" in prompt:
                assert isinstance(response, dict)
                return {**response, "reason": reason}
            return response

    ai = ReasonBackend()
    if error is not None:
        with pytest.raises(ScoringError, match=error) as raised:
            _run(tmp_path, FakeTranscriber(), ai)
        assert str(raised.value).startswith("AI returned invalid score reason:")
        assert "provider-secret" not in str(raised.value)
        assert ai.calls == 2
        corrected_asr, corrected_ai = FakeTranscriber(), FakeBackend()
        corrected = _run(tmp_path, corrected_asr, corrected_ai)
        assert corrected_asr.calls == 0
        assert corrected_ai.calls == 2
        assert json.loads(corrected.manifest_path.read_text(encoding="utf-8"))[
            "analysis"
        ]["ai_cache"] == {"hits": 1, "misses": 2}
    else:
        assert isinstance(reason, str)
        result = _run(tmp_path, FakeTranscriber(), ai)
        assert ai.calls == 3
        assert len(result.clip_paths) == 2
        for path in result.clip_paths:
            metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            assert metadata["viral_potential"]["reason"] == reason.strip()
        repeated_asr, repeated_ai = FakeTranscriber(), ReasonBackend()
        _run(tmp_path, repeated_asr, repeated_ai)
        assert repeated_asr.calls == repeated_ai.calls == 0


def test_long_class_has_no_hard_maximum_and_score_is_weighted() -> None:
    unit = TimedUnit("u0", 0.0, 1200.0, "A complete long discussion.")
    proposal = parse_proposals(
        {
            "clips": [
                {
                    "class": "long",
                    "start_id": "u0",
                    "end_id": "u0",
                    "title": "Long",
                    "rationale": "Full argument",
                }
            ]
        },
        (unit,),
        "sha256-v1:source",
    )[0]
    judged = parse_judgment(
        {
            "start_id": "u0",
            "end_id": "u0",
            "approved": True,
            "dimensions": {
                "hook": 100,
                "standalone_context": 50,
                "development": 80,
                "payoff": 90,
                "interest_novelty": 60,
            },
            "reason": "Clear payoff",
        },
        proposal,
        (unit,),
        "sha256-v1:source",
    )
    assert proposal.end == 1200.0
    assert judged.score == 76.5
    assert select_clips((judged,)) == (judged,)
    low_score = parse_judgment(
        {
            "start_id": "u0",
            "end_id": "u0",
            "approved": True,
            "dimensions": {name: 5 for name in judged.dimensions},
            "reason": "Eligible despite a low relative ranking",
        },
        proposal,
        (unit,),
        "sha256-v1:source",
    )
    assert low_score.score == 5
    assert select_clips((low_score,)) == (low_score,)
    rejected = parse_judgment(
        {
            "start_id": "u0",
            "end_id": "u0",
            "approved": False,
            "dimensions": {name: 100 for name in judged.dimensions},
            "reason": "Lacks a complete editorial idea",
        },
        proposal,
        (unit,),
        "sha256-v1:source",
    )
    assert select_clips((rejected,)) == ()


def test_large_unpunctuated_transcript_is_split_at_observed_boundaries() -> None:
    from multicuts.clips import context_blocks, timed_units

    text = "word " * 50
    transcript = Transcript(
        None,
        "en",
        100.0,
        text * 10,
        tuple(
            TranscriptSegment(text, index * 10.0, (index + 1) * 10.0)
            for index in range(10)
        ),
        (),
        "multisubs",
        "4.3.0",
    )
    units = timed_units(transcript, max_unit_chars=700)
    assert len(units) > 1
    assert units[0].start == 0.0 and units[-1].end == 100.0
    blocks = context_blocks(units, max_chars=1200, overlap_chars=300)
    assert len(blocks) > 1
    assert set(unit.id for unit in blocks[0]) & set(unit.id for unit in blocks[1])


def test_three_minute_boundary_is_short_and_long_starts_above_it() -> None:
    assert (
        parse_proposals(
            {
                "clips": [
                    {
                        "class": "short",
                        "start_id": "u0",
                        "end_id": "u0",
                        "title": "Exact",
                        "rationale": "Complete",
                    }
                ]
            },
            (TimedUnit("u0", 0.0, 180.0, "A complete idea."),),
            "sha256-v1:source",
        )[0].clip_class
        == "short"
    )
    with pytest.raises(ScoringError, match="duration class"):
        parse_proposals(
            {
                "clips": [
                    {
                        "class": "long",
                        "start_id": "u0",
                        "end_id": "u0",
                        "title": "Wrong",
                        "rationale": "Complete",
                    }
                ]
            },
            (TimedUnit("u0", 0.0, 180.0, "A complete idea."),),
            "sha256-v1:source",
        )


def test_judgment_revises_only_observed_nearby_boundaries() -> None:
    units = tuple(
        TimedUnit(f"u{index}", index * 20.0, (index + 1) * 20.0, f"Point {index}.")
        for index in range(5)
    )
    proposal = parse_proposals(
        {
            "clips": [
                {
                    "class": "short",
                    "start_id": "u1",
                    "end_id": "u2",
                    "title": "A title that should not guide the judge",
                    "rationale": "A complete point",
                }
            ]
        },
        units,
        "sha256-v1:source",
    )[0]
    prompt = judgment_prompt(proposal, units)
    assert proposal.title not in prompt
    assert "topic-aware audience" in prompt
    assert "u0 [0.000-20.000]" in prompt
    properties = judgment_schema(proposal, units)["properties"]
    assert isinstance(properties, dict)
    assert properties["start_id"]["enum"] == ["u0", "u1", "u2", "u3", "u4"]
    judged = parse_judgment(
        {
            "start_id": "u0",
            "end_id": "u3",
            "approved": True,
            "dimensions": {
                "hook": 70,
                "standalone_context": 70,
                "development": 70,
                "payoff": 70,
                "interest_novelty": 70,
            },
            "reason": "The revised span gives the idea a complete opening and close",
        },
        proposal,
        units,
        "sha256-v1:source",
    )
    assert (judged.proposal.start, judged.proposal.end) == (0.0, 80.0)
    assert (judged.proposal.start_id, judged.proposal.end_id) == ("u0", "u3")
    assert judged.proposal.text == "Point 0. Point 1. Point 2. Point 3."
    assert judged.proposal.id != proposal.id
    assert (judged.proposed_start_id, judged.proposed_end_id) == ("u1", "u2")


def test_judgment_rejects_boundary_outside_review_window() -> None:
    units = tuple(
        TimedUnit(f"u{index}", index * 5.0, (index + 1) * 5.0, f"Point {index}.")
        for index in range(25)
    )
    proposal = parse_proposals(
        {
            "clips": [
                {
                    "class": "short",
                    "start_id": "u13",
                    "end_id": "u14",
                    "title": "Idea",
                    "rationale": "Complete",
                }
            ]
        },
        units,
        "sha256-v1:source",
    )[0]
    with pytest.raises(ScoringError, match="outside its review window"):
        parse_judgment(
            {
                "start_id": "u0",
                "end_id": "u14",
                "approved": True,
                "dimensions": {
                    "hook": 70,
                    "standalone_context": 70,
                    "development": 70,
                    "payoff": 70,
                    "interest_novelty": 70,
                },
                "reason": "Complete",
            },
            proposal,
            units,
            "sha256-v1:source",
        )


def test_judgment_keeps_revised_clip_in_original_duration_class() -> None:
    units = (
        TimedUnit("u0", 0.0, 100.0, "First point."),
        TimedUnit("u1", 100.0, 170.0, "Second point."),
        TimedUnit("u2", 170.0, 200.0, "Closing point."),
    )
    proposal = parse_proposals(
        {
            "clips": [
                {
                    "class": "short",
                    "start_id": "u0",
                    "end_id": "u1",
                    "title": "Idea",
                    "rationale": "Complete",
                }
            ]
        },
        units,
        "sha256-v1:source",
    )[0]
    with pytest.raises(ScoringError, match="duration class"):
        parse_judgment(
            {
                "start_id": "u0",
                "end_id": "u2",
                "approved": True,
                "dimensions": {
                    "hook": 70,
                    "standalone_context": 70,
                    "development": 70,
                    "payoff": 70,
                    "interest_novelty": 70,
                },
                "reason": "Complete",
            },
            proposal,
            units,
            "sha256-v1:source",
        )


def test_pipeline_publishes_revised_boundary_and_counts_adjustment(
    tmp_path: Path,
) -> None:
    class RevisingBackend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            response = super().complete(prompt, schema)
            if "Original boundary IDs: u0 through u1" in prompt:
                assert isinstance(response, dict)
                return {**response, "start_id": "u1"}
            return response

    result = _run(tmp_path, FakeTranscriber(), RevisingBackend())
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["analysis"]["boundary_adjusted"] == 1
    short_path = next(
        path for path in result.clip_paths if path.parent.parent.name == "shorts"
    )
    short_metadata = json.loads(short_path.with_suffix(".json").read_text())
    assert (short_metadata["start"], short_metadata["end"]) == (60.0, 120.0)
    assert short_metadata["transcript_unit_ids"] == {"start": "u1", "end": "u1"}


def test_pipeline_merges_proposals_revised_to_same_interval(tmp_path: Path) -> None:
    class DuplicateRevisingBackend(FakeBackend):
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            if "Find every" in prompt:
                return {
                    "clips": [
                        {
                            "class": "short",
                            "start_id": "u0",
                            "end_id": "u1",
                            "title": "First version",
                            "rationale": "Complete point",
                        },
                        {
                            "class": "short",
                            "start_id": "u1",
                            "end_id": "u2",
                            "title": "Second version",
                            "rationale": "Complete point",
                        },
                    ]
                }
            response = super().complete(prompt, schema)
            assert isinstance(response, dict)
            return {**response, "start_id": "u1", "end_id": "u1"}

    result = _run(tmp_path, FakeTranscriber(), DuplicateRevisingBackend())
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["analysis"]["proposed"] == 2
    assert manifest["analysis"]["editorially_eligible"] == 1
    assert manifest["analysis"]["selected"] == 1
    assert len(result.clip_paths) == 1


def test_scoped_dimensions_and_styles_reach_final_render_without_extra_asr(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    from multicuts.adapters.multisubs import MultisubsAdapter

    monkeypatch.setattr(
        MultisubsAdapter, "validate_subtitle_options", lambda *a, **k: None
    )
    config = parse_run_config(
        [
            "source.mp4",
            "--output-dir",
            str(tmp_path / "out"),
            "--clip-full",
            "--width",
            "short=720",
            "--width",
            "short:vertical=360",
            "--subtitle-font-size",
            "short:vertical=4%",
        ]
    )
    asr, ai = FakeTranscriber(), FakeBackend()
    result = _run(
        tmp_path, asr, ai, config=config, source_media=replace(_media(), duration=180)
    )
    assert asr.calls == 1 and ai.calls == 0
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text())
    variants = manifest["clips"][0]["variants"]
    assert len(variants) == 6
    for version in variants:
        data = json.loads((root / version["metadata"]).read_text())
        width = 360 if version["variant"] == "vertical" else 720
        assert data["render"]["width"] == width
        if version["variant"] == "vertical":
            assert data["render"]["height"] == 640
            assert data["render"]["subtitle_overrides"] == {"font_size": "4%"}


def test_mismatched_scoped_dimensions_fail_before_asr(tmp_path):
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        full_video=True,
        output_options=(OutputOptions("long", "horizontal", width=720, height=720),),
    )
    asr = FakeTranscriber()
    with pytest.raises(ConfigurationError, match="dimensions must be"):
        _run(tmp_path, asr, FakeBackend(), config=config)
    assert asr.calls == 0


@pytest.mark.parametrize("kind", ["short", "long"])
def test_custom_canvas_metadata_captions_and_cache_follow_dimensions(
    kind, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "multicuts.pipeline.MultisubsAdapter.validate_subtitle_options",
        lambda *a, **k: None,
    )
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "model",
        short_primary="horizontal-blur",
        long_primary="horizontal-blur",
        render="primary",
        output_options=(
            OutputOptions(
                kind,
                "horizontal-blur",
                width=2520,
                height=1080,
                subtitle_options=SubtitleOptions(font_size="4%"),
            ),
        ),
    )
    first = _run(tmp_path, FakeTranscriber(), FakeBackend(), config=config)
    primary = next(
        path
        for path in first.clip_paths
        if json.loads(path.with_suffix(".json").read_text())["class"] == kind
    )
    metadata = json.loads(primary.with_suffix(".json").read_text())
    assert (metadata["render"]["width"], metadata["render"]["height"]) == (2520, 1080)
    assert metadata["render"]["aspect_ratio"] == "7:3"
    assert metadata["render"]["variant"] == "horizontal-blur"
    assert metadata["render"]["subtitle_overrides"] == {"font_size": "4%"}
    assert len(metadata["subtitle_files"]) == 3
    asr, ai = FakeTranscriber(), FakeBackend()
    second = _run(
        tmp_path,
        asr,
        ai,
        config=replace(
            config,
            output_options=(
                OutputOptions(kind, "horizontal-blur", width=1600, height=1000),
            ),
        ),
    )
    assert asr.calls == ai.calls == 0
    primary = next(
        path
        for path in second.clip_paths
        if json.loads(path.with_suffix(".json").read_text())["class"] == kind
    )
    metadata = json.loads(primary.with_suffix(".json").read_text())
    assert (metadata["render"]["width"], metadata["render"]["height"]) == (1600, 1000)
    assert metadata["render"]["aspect_ratio"] == "8:5"


@pytest.mark.parametrize("kind", ["short", "long"])
@pytest.mark.parametrize(
    ("dimensions", "expected"),
    [
        ((1920, 1080), {"horizontal-blur": (656, 606), "square-blur": (236, 606)}),
        ((900, 1200), {"horizontal-blur": (554, 810), "square-blur": (134, 810)}),
        ((720, 720), {"horizontal-blur": (656, 606)}),
    ],
)
def test_blur_subtitle_containers_follow_the_source_and_keep_vertical_blur_full_canvas(
    kind, dimensions, expected, tmp_path, monkeypatch
):
    validated = []
    monkeypatch.setattr(
        "multicuts.pipeline.MultisubsAdapter.validate_subtitle_options",
        lambda _self, **settings: validated.append(settings),
    )
    config = AppConfig(
        "source.mp4",
        tmp_path / "out",
        "codex",
        "test-model",
        subtitles_enabled=True,
        short_render=kind == "short",
        long_render=kind == "long",
        subtitle_options=SubtitleOptions(position="top-left"),
    )
    transcriber = FakeTranscriber()
    result = _run(
        tmp_path,
        transcriber,
        FakeBackend(),
        config=config,
        source_media=_media(*dimensions),
    )
    assert transcriber.calls == 1
    assert validated == [
        {
            "template": "yellow-pop",
            "template_dir": None,
            "options": config.subtitle_options,
        }
    ]
    manifest = json.loads(result.manifest_path.read_text())
    for cut in manifest["clips"]:
        for version in cut["variants"]:
            metadata = json.loads(
                (result.manifest_path.parent / version["metadata"]).read_text()
            )
            name = version["variant"]
            render = metadata["render"]
            if name in expected:
                left, width = expected[name]
                assert render["subtitle_container"] == {
                    "x": left,
                    "y": 0,
                    "width": width,
                    "height": 1080,
                }
            else:
                assert render["subtitle_container"] is None
            assert render["subtitle_overrides"] == {"position": "top-left"}


def test_parallel_cuts_overlap_and_preserve_rank_and_single_transcription(tmp_path):
    from threading import Barrier, Event

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    both_started = Barrier(2, timeout=5)
    long_finished = Event()
    completion = []
    asr = FakeTranscriber()

    def raw(acquired, media, clip, config, *, output, work, should_cancel):
        both_started.wait()
        if clip.proposal.clip_class == "short":
            assert long_finished.wait(5)
        assert not should_cancel()
        output.parent.mkdir(parents=True)
        output.write_bytes(b"raw")
        return (
            output,
            media,
            config.aspect_ratio_for(clip.proposal.clip_class, "horizontal"),
        )

    def final(
        raw_path, media, transcript, clip, config, *, output, work, should_cancel
    ):
        assert not should_cancel()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"final")
        completion.append(clip.proposal.clip_class)
        if clip.proposal.clip_class == "long":
            long_finished.set()
        return output, (), None

    result = run_pipeline(
        AppConfig(
            str(source),
            tmp_path / "out",
            "codex",
            "test",
            render="primary",
            subtitles_enabled=False,
            render_jobs=2,
        ),
        acquire=lambda *args, **kwargs: AcquiredSource(source, "parallel"),
        probe=lambda _: _media(),
        transcriber=asr,
        backend=FakeBackend(),
        raw_renderer=raw,
        final_renderer=final,
    )
    manifest = json.loads(result.manifest_path.read_text())
    assert asr.calls == 1
    assert completion == ["long", "short"]
    assert [clip["class"] for clip in manifest["clips"]] == ["short", "long"]
    assert [
        json.loads(path.with_suffix(".json").read_text())["rank"]
        for path in result.clip_paths
    ] == [1, 2]
    assert manifest["execution"]["render_jobs"] == 2
    assert not (result.manifest_path.parent / ".work").exists()


def _fake_composed_output(
    media: MediaInfo,
    clip: JudgedClip | DirectClip,
    config: AppConfig,
    *,
    output: Path,
    work: Path,
) -> RenderedVariant:
    assert config.render_variant is not None
    width, height = config.dimensions_for(
        clip.proposal.clip_class, config.render_variant
    )
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"complete variant")
    return RenderedVariant(
        output,
        replace(
            media,
            duration=clip.proposal.end - clip.proposal.start,
            coded_width=width,
            coded_height=height,
            presentation_width=width,
            presentation_height=height,
        ),
        config.aspect_ratio_for(clip.proposal.clip_class, config.render_variant),
    )


@pytest.mark.parametrize("single_cut", [False, True])
def test_parallel_variants_share_one_global_limit_and_keep_output_order(
    tmp_path, single_cut, caplog
):
    from threading import Barrier, Event, Lock

    caplog.set_level(logging.INFO, logger="multicuts.pipeline")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    first_wave = Barrier(3, timeout=5)
    additional_finished = Event()
    lock = Lock()
    active = peak = finished = 0
    started = []
    completion = []
    workspaces = []
    transcripts = set()
    cut_count = 1 if single_cut else 2
    asr = FakeTranscriber()

    def composed(
        acquired, media, transcript, clip, config, *, output, work, should_cancel
    ):
        nonlocal active, peak, finished
        name = config.render_variant
        with lock:
            active += 1
            peak = max(peak, active)
            started.append((clip.proposal.clip_class, name))
            ordinal = len(started)
            workspaces.append(work)
            transcripts.add(id(transcript))
        try:
            if ordinal <= 3:
                first_wave.wait()
            if name == "horizontal":
                assert additional_finished.wait(5)
            assert not should_cancel()
            rendered = _fake_composed_output(
                media, clip, config, output=output, work=work
            )
            with lock:
                completion.append(name)
                if name != "horizontal":
                    finished += 1
                    if finished == 5 * cut_count:
                        assert any(
                            re.match(r"Clip \d+/\d+ version \S+ saved:", message)
                            for message in caplog.messages
                        )
                        assert not any(
                            re.match(r"Clip \d+/\d+ saved:", message)
                            for message in caplog.messages
                        )
                        additional_finished.set()
            return rendered
        finally:
            with lock:
                active -= 1

    config = AppConfig(
        str(source),
        tmp_path / "out",
        "" if single_cut else "codex",
        "" if single_cut else "test",
        full_video=single_cut,
        render_jobs=3,
    )
    result = run_pipeline(
        config,
        acquire=lambda *args, **kwargs: AcquiredSource(source, "parallel-variants"),
        probe=lambda _: _media(),
        transcriber=asr,
        backend=FakeBackend(),
        composed_renderer=composed,
    )
    assert asr.calls == 1
    assert peak == 3 and active == 0
    assert len(started) == len(set(workspaces)) == cut_count * 6
    assert len(transcripts) == 1
    assert completion[-cut_count:] == ["horizontal"] * cut_count
    version_logs = [
        message
        for message in caplog.messages
        if re.match(r"Clip \d+/\d+ version \S+ saved:", message)
    ]
    assert len(version_logs) == cut_count * 6
    assert all(re.search(r"\(\d+\.\ds\)$", message) for message in version_logs)
    manifest = json.loads(result.manifest_path.read_text())
    assert len(manifest["clips"]) == cut_count
    for rank, reference in enumerate(manifest["clips"], start=1):
        assert [version["variant"] for version in reference["variants"]] == list(
            VARIANTS
        )
        assert reference["video"] == reference["variants"][0]["video"]
        for index, version in enumerate(reference["variants"]):
            metadata = json.loads(
                (result.manifest_path.parent / version["metadata"]).read_text()
            )
            assert metadata["rank"] == rank
            assert metadata["render"]["is_variant"] is (index != 0)
    if not single_cut:
        assert [cut["class"] for cut in manifest["clips"]] == ["short", "long"]
    assert not (result.manifest_path.parent / ".work").exists()


@pytest.mark.parametrize("short_primary_only", [False, True])
def test_primary_variants_lead_then_additional_variants_rotate_between_cuts(
    tmp_path, short_primary_only
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    started = []

    def composed(acquired, media, transcript, clip, config, *, output, work):
        started.append((clip.proposal.clip_class, config.render_variant))
        return _fake_composed_output(media, clip, config, output=output, work=work)

    config = AppConfig(
        str(source),
        tmp_path / "out",
        "codex",
        "test",
        short_render="primary" if short_primary_only else True,
        short_primary="vertical",
        long_primary="square",
        subtitles_enabled=False,
    )
    result = run_pipeline(
        config,
        acquire=lambda *args, **kwargs: AcquiredSource(source, "variant-priority"),
        probe=lambda _: _media(),
        transcriber=FakeTranscriber(),
        backend=FakeBackend(),
        composed_renderer=composed,
    )
    assert started[:2] == [("short", "vertical"), ("long", "square")]
    assert [kind for kind, _ in started[2:]] == (
        ["long"] * 5 if short_primary_only else ["short", "long"] * 5
    )
    manifest = json.loads(result.manifest_path.read_text())
    for clip in manifest["clips"]:
        names = config.outputs_for(clip["class"], _media())
        assert [name for kind, name in started if kind == clip["class"]] == list(names)
        assert [version["variant"] for version in clip["variants"]] == list(names)


@pytest.mark.parametrize("interrupted", [False, True])
def test_variant_failure_cancels_peer_preserves_completed_output_and_stops_queue(
    tmp_path, caplog, interrupted
):
    from threading import Event, Lock

    from multicuts.errors import RenderingCancelledError, RenderingError

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    peer_started, peer_stopped = Event(), Event()
    lock = Lock()
    started = []
    failure = KeyboardInterrupt if interrupted else RenderingError
    caplog.set_level(logging.INFO, logger="multicuts.pipeline")

    def composed(
        acquired, media, transcript, clip, config, *, output, work, should_cancel
    ):
        name = config.render_variant
        with lock:
            started.append(name)
        if name == "horizontal":
            return _fake_composed_output(media, clip, config, output=output, work=work)
        if name == "vertical":
            assert peer_started.wait(5)
            raise failure("original variant failure")
        assert name == "square", "A later variant started after the failure"
        work.mkdir(parents=True, exist_ok=True)
        peer_started.set()
        try:
            for _ in range(500):
                if should_cancel():
                    raise RenderingCancelledError("peer cancelled")
                peer_stopped.wait(0.01)
            pytest.fail("Active variant did not receive cancellation")
        finally:
            assert work.exists(), "Workspace cleaned before the active render stopped"
            peer_stopped.set()

    with pytest.raises(failure, match="original variant failure"):
        run_pipeline(
            AppConfig(
                str(source),
                tmp_path / "out",
                full_video=True,
                subtitles_enabled=False,
                render_jobs=2,
            ),
            acquire=lambda *args, **kwargs: AcquiredSource(source, "variant-failure"),
            probe=lambda _: _media(),
            composed_renderer=composed,
        )
    assert set(started) == {"horizontal", "vertical", "square"}
    assert peer_stopped.is_set()
    (run_root,) = (tmp_path / "out" / "runs").iterdir()
    (complete,) = run_root.glob("longs/*/horizontal.mp4")
    assert complete.with_suffix(".json").is_file()
    assert not (run_root / "manifest.json").exists()
    assert not (run_root / "report.md").exists()
    assert not (run_root / ".work").exists()
    assert "Clip 1/1 saved" not in caplog.text
    assert "Clip 1/1 version horizontal saved:" in caplog.text
    assert "Clip 1/1 version vertical saved:" not in caplog.text
    assert "Clip 1/1 version square saved:" not in caplog.text


def test_parallel_failure_cancels_active_peer_and_does_not_schedule_more(tmp_path):
    from threading import Barrier, Event

    from multicuts.errors import RenderingCancelledError, RenderingError

    class Backend(FakeBackend):
        def complete(self, prompt, schema):
            if "Find every" in prompt:
                return {
                    "clips": [
                        {
                            "class": "short",
                            "start_id": f"u{i}",
                            "end_id": f"u{i}",
                            "title": f"Cut {i}",
                            "rationale": "Complete idea",
                        }
                        for i in (0, 2, 4)
                    ]
                }
            return super().complete(prompt, schema)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    started = []
    both_started = Barrier(2, timeout=5)
    peer_stopped = Event()

    def raw(acquired, media, clip, config, *, output, work, should_cancel):
        started.append(clip.proposal.start_id)
        both_started.wait()
        if clip.proposal.start_id == "u0":
            raise RenderingError("original render failure")
        try:
            for _ in range(500):
                if should_cancel():
                    raise RenderingCancelledError("peer cancelled")
                peer_stopped.wait(0.01)
            pytest.fail("Active peer did not receive cancellation")
        finally:
            peer_stopped.set()

    with pytest.raises(RenderingError, match="original render failure"):
        run_pipeline(
            AppConfig(
                str(source),
                tmp_path / "out",
                "codex",
                "test",
                render="primary",
                render_jobs=2,
            ),
            acquire=lambda *args, **kwargs: AcquiredSource(source, "parallel-failure"),
            probe=lambda _: _media(),
            transcriber=FakeTranscriber(),
            backend=Backend(),
            raw_renderer=raw,
        )
    assert set(started) == {"u0", "u2"}
    assert peer_stopped.is_set()
    assert not list((tmp_path / "out" / "runs").glob("*/manifest.json"))
    assert not list((tmp_path / "out" / "runs").glob("*/.work"))
