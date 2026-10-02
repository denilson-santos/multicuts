"""Hermetic checks for semantic selection, reruns, and run artifacts."""

import json
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.app_config import AppConfig
from multicuts.clips import (
    TimedUnit,
    judgment_prompt,
    judgment_schema,
    parse_judgment,
    parse_proposals,
    select_clips,
)
from multicuts.errors import ScoringError
from multicuts.models import AcquiredSource, MediaInfo, Transcript, TranscriptSegment
from multicuts.pipeline import run_pipeline


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls = 0

    def version(self) -> str:
        return "4.3.0"

    def transcribe(
        self, video_path: Path, *, language: str | None, model: str, workspace: Path
    ) -> Transcript:
        self.calls += 1
        return Transcript(
            language_requested=language,
            language_detected="en",
            duration=360.0,
            text=" ".join(f"Point {index}." for index in range(6)),
            segments=tuple(
                TranscriptSegment(f"Point {index}.", index * 60.0, (index + 1) * 60.0)
                for index in range(6)
            ),
            words=(),
            provider="multisubs",
            provider_version=self.version(),
        )


class FakeBackend:
    def __init__(self, *, empty: bool = False, invalid: bool = False) -> None:
        self.calls = 0
        self.empty = empty
        self.invalid = invalid

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        self.calls += 1
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


def _run(
    tmp_path: Path,
    transcriber: FakeTranscriber,
    backend: FakeBackend,
    *,
    config: AppConfig | None = None,
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

    def acquire(_source: str, _workspace: Path) -> AcquiredSource:
        return AcquiredSource(source_file, "sha256-v1:source")

    def raw_renderer(
        _source: AcquiredSource,
        _media: MediaInfo,
        clip,
        _config: AppConfig,
        *,
        output: Path,
        work: Path,
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"raw")
        if clip.proposal.clip_class == "short":
            return output, _media_factory(1080, 1920), "9:16"
        return output, _media_factory(1920, 1080), "16:9"

    def _media_factory(width: int, height: int) -> MediaInfo:
        return _media(width, height)

    def final_renderer(
        raw: Path,
        raw_media: MediaInfo,
        transcript: Transcript,
        clip,
        _config: AppConfig,
        *,
        output: Path,
        work: Path,
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, output)
        return output, (), None

    return run_pipeline(
        current,
        acquire=acquire,
        probe=lambda _: _media(),
        transcriber=transcriber,
        backend=backend,
        raw_renderer=raw_renderer,
        final_renderer=final_renderer,
    )


def test_rerun_reuses_transcription_and_ai_but_publishes_fresh_clips(
    tmp_path: Path,
) -> None:
    first_asr = FakeTranscriber()
    first_ai = FakeBackend()
    first = _run(tmp_path, first_asr, first_ai)
    assert first_asr.calls == 1
    assert first_ai.calls == 3
    assert len(first.clip_paths) == 2
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
    assert set(first.clip_paths).isdisjoint(second.clip_paths)
    manifest = json.loads(second.manifest_path.read_text())
    assert manifest["transcription"]["cache_hit"] is True
    assert manifest["analysis"]["ai_cache"] == {"hits": 3, "misses": 0}
    assert manifest["schema_version"] == 3
    assert manifest["analysis"]["editorially_eligible"] == 2
    assert manifest["analysis"]["selected"] == 2
    assert "minimum_score" not in manifest["analysis"]


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


def test_effort_change_reuses_asr_but_recomputes_ai(tmp_path: Path) -> None:
    base = AppConfig(
        "source.mp4", tmp_path / "out", "codex", "model-a", subtitles_enabled=False
    )
    _run(tmp_path, FakeTranscriber(), FakeBackend(), config=base)
    config = replace(base, llm_effort="high")
    asr = FakeTranscriber()
    ai = FakeBackend()
    result = _run(tmp_path, asr, ai, config=config)
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


def test_invalid_ai_response_fails_explicitly_and_is_not_cached(tmp_path: Path) -> None:
    invalid = FakeBackend(invalid=True)
    with pytest.raises(ScoringError):
        _run(tmp_path, FakeTranscriber(), invalid)
    valid = FakeBackend()
    _run(tmp_path, FakeTranscriber(), valid)
    assert valid.calls == 3


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
    short_path = next(path for path in result.clip_paths if "short" in path.name)
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
