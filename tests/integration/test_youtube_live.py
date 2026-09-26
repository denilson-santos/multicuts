import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from multicuts.adapters.youtube import YoutubeAdapter
from multicuts.config import RunConfig
from multicuts.final_artifacts import ClipOutcome, RunOutcome, read_manifest_payload
from multicuts.media import inspect_media_path, probe_media
from multicuts.models import (
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationBatch,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import run_pipeline


@pytest.mark.integration
def test_youtube_adapter_against_explicit_fixture_source(tmp_path: Path) -> None:
    source = os.environ.get("MULTICUTS_YOUTUBE_TEST_URL")
    if not source:
        pytest.skip("set MULTICUTS_YOUTUBE_TEST_URL to run the live YouTube check")
    assert source is not None

    acquired = YoutubeAdapter().acquire(source, tmp_path / "downloads")

    assert acquired.source_kind == "youtube"
    assert acquired.provider_id
    assert acquired.title
    assert acquired.local_path.is_file()
    assert acquired.local_path.is_relative_to((tmp_path / "downloads").resolve())


@pytest.mark.integration
def test_youtube_pipeline_from_live_acquisition_to_output(tmp_path: Path) -> None:
    source_url = os.environ.get("MULTICUTS_YOUTUBE_TEST_URL")
    if not source_url:
        pytest.skip("set MULTICUTS_YOUTUBE_TEST_URL to run the live YouTube flow")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required")
    if importlib.util.find_spec("yt_dlp") is None:
        pytest.skip("yt-dlp is required")

    acquired = YoutubeAdapter().acquire(source_url, tmp_path / "downloads")
    media = probe_media(acquired)
    if media.duration <= 3.0 or not media.has_audio:
        pytest.skip("the YouTube fixture needs audio and more than 3 seconds")
    start = 0.1
    end = min(4.0, media.duration - 0.1)
    sentence = "A complete thought."
    transcript = Transcript(
        None,
        "en",
        media.duration,
        sentence,
        (TranscriptSegment(sentence, start, end),),
        (
            Word("A", start, 0.35),
            Word("complete", 0.4, 0.8),
            Word("thought.", 0.9, 1.4),
        ),
        "multisubs",
        "4.3.0",
    )
    candidate = Candidate("candidate-v1:youtube-live", start, end, sentence, (0,), "1")
    evaluation = CandidateEvaluation(
        candidate,
        CandidateFeatures(
            duration=end - start,
            word_count=3,
            timed_word_count=3,
            words_per_second=3 / (end - start),
        ),
        (ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        1,
    )
    batch = CandidateEvaluationBatch((evaluation,), (evaluation,))

    class FixtureTranscriber:
        def __init__(self) -> None:
            self.calls = 0

        def version(self) -> str:
            return "4.3.0"

        def transcribe(
            self,
            video_path: Path,
            *,
            language: str | None,
            model: str,
            workspace: Path,
        ) -> Transcript:
            del language, model, workspace
            assert video_path == acquired.local_path
            self.calls += 1
            return transcript

    transcriber = FixtureTranscriber()
    config = RunConfig(
        source=source_url,
        output_dir=tmp_path / "output",
        clips=1,
        min_score=0,
        aspect_ratio="original",
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
        subtitles_enabled=False,
        min_duration=2.0,
        max_duration=4.0,
        refinement_pre_roll=0.0,
        refinement_post_roll=0.0,
    )
    result = run_pipeline(
        config,
        acquire=lambda _source, _workspace: acquired,
        probe=probe_media,
        transcriber=transcriber,
        candidate_generator=lambda *_args, **_kwargs: (candidate,),
        candidate_evaluator=lambda *_args, **_kwargs: batch,
    )

    assert result.outcome is RunOutcome.COMPLETED
    assert len(result.clip_paths) == 1
    assert transcriber.calls == 1
    final_media = inspect_media_path(result.clip_paths[0])
    assert final_media.duration == pytest.approx(end - start, abs=0.25)
    manifest = read_manifest_payload(
        json.loads(result.manifest_path.read_text(encoding="utf-8"))
    )
    assert manifest.source.kind == "youtube"
    assert manifest.source.reference.endswith(f"v={acquired.provider_id}")
    assert manifest.clips[0].status is ClipOutcome.COMPLETED
    assert result.clip_paths[0].with_suffix(".json").is_file()
