import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from multicuts.adapters.scoring import OpenAISemanticAdapter
from multicuts.config import RunConfig
from multicuts.errors import ScoringError
from multicuts.models import (
    SCORE_DIMENSIONS,
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationArtifact,
    CandidateFeatures,
    CandidateScoringFailure,
    ChecklistOutcome,
    ChecklistResult,
    ScoredCandidate,
    ScoreDimension,
    ScoringBatch,
    ScoringProvenance,
    SemanticJudgment,
    SemanticScoringRequest,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import load_or_score_candidates, load_or_select_candidates
from multicuts.scoring.artifacts import scoring_cache_key
from multicuts.scoring.heuristic import score_heuristically
from multicuts.scoring.hybrid import compose_hybrid_score
from multicuts.scoring.semantic import (
    SEMANTIC_PROMPT_VERSION,
    SemanticProviderError,
    build_semantic_request,
)


def _evaluation(**feature_changes: float | None) -> CandidateEvaluation:
    values = {
        "duration": 30.0,
        "word_count": 20,
        "timed_word_count": 20,
        "words_per_second": 2.0,
        "pause_ratio": 0.1,
        "opening_quality": 0.8,
        "ending_quality": 0.75,
        "standalone_context": 0.7,
        "payoff": 0.9,
        "filler_ratio": 0.1,
        "transcript_confidence": 0.8,
        "timing_coverage": 1.0,
    }
    values.update(feature_changes)
    return CandidateEvaluation(
        candidate=Candidate(
            "candidate-v1:semantic",
            10.0,
            40.0,
            "A clear standalone candidate with a payoff.",
            (1,),
            "1",
        ),
        features=CandidateFeatures(**values),  # type: ignore[arg-type]
        checklist=(ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        shortlist_rank=1,
    )


def _transcript() -> Transcript:
    return Transcript(
        language_requested=None,
        language_detected="en",
        duration=60.0,
        text="Full normalized transcript",
        segments=(
            TranscriptSegment("B" * 600, 0.0, 9.0),
            TranscriptSegment("A clear standalone candidate with a payoff.", 10, 40),
            TranscriptSegment("C" * 600, 41.0, 50.0),
        ),
        words=(),
        provider="multisubs",
        provider_version="4.2.0",
    )


def _judgment(value: float = 80.0) -> SemanticJudgment:
    return SemanticJudgment(
        dimensions=tuple(ScoreDimension(name, value) for name in SCORE_DIMENSIONS),
        confidence=0.9,
        reason="The candidate is clear and self-contained.",
        provider="openai",
        model="gpt-6-luna",
        prompt_version=SEMANTIC_PROMPT_VERSION,
    )


def _valid_response() -> str:
    return json.dumps(
        {
            "dimensions": {name: 80 for name in SCORE_DIMENSIONS},
            "confidence": 0.9,
            "reason": "The candidate is clear and self-contained.",
        }
    )


class _Response:
    def __init__(self, output_text: str, *, status: str | None = None) -> None:
        self.output_text = output_text
        if status is not None:
            self.status = status


class _Responses:
    def __init__(self, outcomes: list[str | Exception | _Response]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome) if isinstance(outcome, str) else outcome


class _Client:
    def __init__(self, outcomes: list[str | Exception | _Response]) -> None:
        self.responses = _Responses(outcomes)


class _FakeSemanticScorer:
    def __init__(self, outcome: SemanticJudgment | SemanticProviderError) -> None:
        self.outcome = outcome
        self.calls = 0

    def score(self, request: SemanticScoringRequest) -> SemanticJudgment:
        self.calls += 1
        assert request.candidate_id
        if isinstance(self.outcome, SemanticProviderError):
            raise self.outcome
        return self.outcome


class _SequencedSemanticScorer:
    def __init__(
        self, outcomes: list[SemanticJudgment | SemanticProviderError]
    ) -> None:
        self.outcomes = outcomes

    def score(self, request: SemanticScoringRequest) -> SemanticJudgment:
        assert request.candidate_id
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, SemanticProviderError):
            raise outcome
        return outcome


def _config(tmp_path: Path, *, fallback: str = "heuristic") -> RunConfig:
    return RunConfig(
        source="source.mp4",
        output_dir=tmp_path,
        clips=2,
        min_score=0,
        aspect_ratio="original",
        subtitle_template="yellow-pop",
        scorer="hybrid",
        model="default",
        semantic_fallback=fallback,
    )


def _artifact(source: AcquiredSource) -> CandidateEvaluationArtifact:
    return CandidateEvaluationArtifact(
        source_fingerprint=source.fingerprint,
        candidate_generator_version="1",
        evaluation_version="1",
        min_duration=15,
        max_duration=60,
        candidate_budget=50,
        evaluations=(_evaluation(),),
    )


def test_semantic_request_limits_surrounding_text_without_media() -> None:
    request = build_semantic_request(_evaluation(), _transcript())

    assert request.candidate_text == "A clear standalone candidate with a payoff."
    assert request.context_before == "B" * 500
    assert request.context_after == "C" * 500
    assert request.candidate_id == "candidate-v1:semantic"


def test_semantic_request_uses_timed_words_when_segments_are_untimed() -> None:
    transcript = replace(
        _transcript(),
        segments=(TranscriptSegment("Untimed transcript text", None, None),),
        words=(
            Word("Earlier", 0.0, 1.0),
            Word("A", 10.0, 11.0),
            Word("payoff", 39.0, 40.0),
            Word("Later", 41.0, 42.0),
        ),
    )

    request = build_semantic_request(_evaluation(), transcript)

    assert request.context_before == "Earlier"
    assert request.context_after == "Later"


def test_openai_adapter_uses_luna_max_structured_stateless_request() -> None:
    client = _Client([_valid_response()])
    adapter = OpenAISemanticAdapter(client)

    result = adapter.score(build_semantic_request(_evaluation(), _transcript()))

    assert result == _judgment()
    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-6-luna"
    assert call["reasoning"] == {"effort": "max"}
    assert call["store"] is False
    text_config = call["text"]
    assert isinstance(text_config, dict)
    structured_format = text_config["format"]
    assert isinstance(structured_format, dict)
    assert structured_format["type"] == "json_schema"
    assert structured_format["strict"] is True
    sent = json.loads(str(call["input"]))
    assert set(sent) == {
        "candidate_text",
        "context_before",
        "context_after",
        "derived_features",
    }
    assert "candidate_id" not in sent


def test_openai_adapter_retries_only_transient_failures() -> None:
    class RateLimitError(Exception):
        status_code = 429

    client = _Client([RateLimitError(), RateLimitError(), _valid_response()])
    delays: list[float] = []
    adapter = OpenAISemanticAdapter(client, sleeper=delays.append)

    assert adapter.score(build_semantic_request(_evaluation(), _transcript()))
    assert len(client.responses.calls) == 3
    assert delays == [0.25, 0.5]

    malformed = _Client(["not-json", _valid_response()])
    with pytest.raises(SemanticProviderError, match="invalid JSON"):
        OpenAISemanticAdapter(malformed).score(
            build_semantic_request(_evaluation(), _transcript())
        )
    assert len(malformed.responses.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda payload: payload["dimensions"].pop("hook"),
        lambda payload: payload["dimensions"].__setitem__("hook", 101),
        lambda payload: payload.__setitem__("confidence", float("nan")),
    ],
)
def test_openai_adapter_rejects_incomplete_or_out_of_range_responses(
    change: object,
) -> None:
    payload = json.loads(_valid_response())
    assert callable(change)
    change(payload)
    client = _Client([json.dumps(payload)])

    with pytest.raises(SemanticProviderError, match="invalid|out-of-range"):
        OpenAISemanticAdapter(client).score(
            build_semantic_request(_evaluation(), _transcript())
        )

    assert len(client.responses.calls) == 1


def test_openai_adapter_retries_connection_failures() -> None:
    class APIConnectionError(Exception):
        pass

    client = _Client([APIConnectionError(), _valid_response()])
    delays: list[float] = []

    result = OpenAISemanticAdapter(client, sleeper=delays.append).score(
        build_semantic_request(_evaluation(), _transcript())
    )

    assert result == _judgment()
    assert delays == [0.25]


def test_openai_adapter_rejects_incomplete_response_with_valid_json() -> None:
    client = _Client([_Response(_valid_response(), status="incomplete")])

    with pytest.raises(SemanticProviderError, match="did not complete"):
        OpenAISemanticAdapter(client).score(
            build_semantic_request(_evaluation(), _transcript())
        )

    assert len(client.responses.calls) == 1


def test_openai_adapter_requires_environment_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ScoringError, match="OPENAI_API_KEY"):
        OpenAISemanticAdapter.from_environment()


@pytest.mark.parametrize(
    ("environment_key", "expected_key"),
    [(None, "dotenv-key"), ("environment-key", "environment-key")],
)
def test_openai_adapter_reads_dotenv_with_environment_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_key: str | None,
    expected_key: str,
) -> None:
    (tmp_path / ".env").write_text('OPENAI_API_KEY="dotenv-key"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    if environment_key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", environment_key)

    captured: dict[str, object] = {}

    def client_factory(**kwargs: object) -> _Client:
        captured.update(kwargs)
        return _Client([])

    monkeypatch.setattr(
        "multicuts.adapters.scoring.import_module",
        lambda name: SimpleNamespace(OpenAI=client_factory),
    )

    OpenAISemanticAdapter.from_environment()

    assert captured["api_key"] == expected_key


def test_hybrid_pipeline_requires_credential_before_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:semantic")

    with pytest.raises(ScoringError, match="OPENAI_API_KEY"):
        load_or_score_candidates(
            _config(tmp_path), source, _transcript(), _artifact(source)
        )

    assert not list(tmp_path.rglob("scores.json"))


def test_hybrid_composition_uses_semantic_dimensions_and_penalties_once() -> None:
    result = compose_hybrid_score(
        _evaluation(duration=20.0, pause_ratio=0.6, filler_ratio=0.4), _judgment()
    )

    assert result.base_score == 80
    assert result.score == 65
    assert result.scorer == "hybrid"
    assert result.provider == "openai"
    assert [item.code for item in result.penalties] == [
        "DURATION_FIT",
        "PAUSE_PROXY",
        "FILLER",
    ]


def test_hybrid_pipeline_reuses_provider_aware_cache_without_credentials(
    tmp_path: Path,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:semantic")
    config = _config(tmp_path)
    scorer = _FakeSemanticScorer(_judgment())

    first = load_or_score_candidates(
        config,
        source,
        _transcript(),
        _artifact(source),
        semantic_scorer=scorer,
    )
    second = load_or_score_candidates(
        config,
        source,
        _transcript(),
        _artifact(source),
    )

    assert first == second
    assert first.scores[0].result.scorer == "hybrid"
    assert first.failures == ()
    assert scorer.calls == 1


@pytest.mark.parametrize(
    ("fallback", "score_count", "expected_scorer"),
    [("heuristic", 1, "heuristic-fallback"), ("none", 0, None)],
)
def test_hybrid_failure_is_persisted_with_explicit_fallback_behavior(
    tmp_path: Path,
    fallback: str,
    score_count: int,
    expected_scorer: str | None,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:semantic")
    config = _config(tmp_path, fallback=fallback)
    scorer = _FakeSemanticScorer(
        SemanticProviderError(
            "rate_limit", "Semantic provider rate limit was reached", retryable=True
        )
    )
    artifact = _artifact(source)

    batch = load_or_score_candidates(
        config,
        source,
        _transcript(),
        artifact,
        semantic_scorer=scorer,
    )

    assert len(batch.scores) == score_count
    assert len(batch.failures) == 1
    assert batch.failures[0].code == "rate_limit"
    cached = load_or_score_candidates(config, source, _transcript(), artifact)
    assert cached == batch
    if expected_scorer is not None:
        assert batch.scores[0].result.scorer == expected_scorer
        assert batch.scores[0].result.provider is None
    else:
        selection = load_or_select_candidates(
            config, source, _transcript(), artifact, batch.scores
        )
        assert selection.selected == selection.decisions == ()


def test_hybrid_fallback_uses_the_injected_heuristic_scorer(tmp_path: Path) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:semantic")
    calls = 0

    def local_scorer(evaluation: CandidateEvaluation):
        nonlocal calls
        calls += 1
        return replace(score_heuristically(evaluation), reason="Injected fallback")

    batch = load_or_score_candidates(
        _config(tmp_path),
        source,
        _transcript(),
        _artifact(source),
        scorer=local_scorer,
        semantic_scorer=_FakeSemanticScorer(
            SemanticProviderError("timeout", "Provider timed out", retryable=True)
        ),
    )

    assert calls == 1
    assert batch.scores[0].result.scorer == "heuristic-fallback"
    assert batch.scores[0].result.reason == "Injected fallback"


def test_one_semantic_failure_does_not_erase_successful_candidate(
    tmp_path: Path,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:semantic")
    first = _evaluation()
    second = replace(
        first,
        candidate=replace(
            first.candidate,
            candidate_id="candidate-v1:second",
            unit_indexes=(2,),
        ),
        shortlist_rank=2,
    )
    artifact = replace(_artifact(source), evaluations=(first, second))
    scorer = _SequencedSemanticScorer(
        [
            _judgment(),
            SemanticProviderError(
                "authentication",
                "Semantic provider credentials were rejected",
                retryable=False,
            ),
        ]
    )
    config = _config(tmp_path, fallback="none")

    batch = load_or_score_candidates(
        config,
        source,
        _transcript(),
        artifact,
        semantic_scorer=scorer,
    )
    selection = load_or_select_candidates(
        config, source, _transcript(), artifact, batch.scores
    )

    assert [item.candidate_id for item in batch.scores] == ["candidate-v1:semantic"]
    assert [item.candidate_id for item in batch.failures] == ["candidate-v1:second"]
    assert [item.candidate_id for item in selection.selected] == [
        "candidate-v1:semantic"
    ]


def test_semantic_configuration_changes_scoring_cache_identity() -> None:
    evaluation = _evaluation()
    base = {
        "evaluation_key": "sha256-v1:evaluation",
        "shortlist": (evaluation,),
        "scorer": "hybrid",
        "semantic_provider": "openai",
        "semantic_model": "gpt-6-luna",
        "semantic_prompt_version": SEMANTIC_PROMPT_VERSION,
        "semantic_reasoning_effort": "max",
        "semantic_fallback": "heuristic",
    }
    key = scoring_cache_key(**base)  # type: ignore[arg-type]

    for field, value in (
        ("semantic_provider", "different"),
        ("semantic_model", "different"),
        ("semantic_prompt_version", "different"),
        ("semantic_reasoning_effort", "high"),
        ("semantic_fallback", "none"),
    ):
        assert (
            scoring_cache_key(
                **{**base, field: value}  # type: ignore[arg-type]
            )
            != key
        )


def test_hybrid_algorithm_versions_change_scoring_cache_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluation = _evaluation()
    options = {
        "evaluation_key": "sha256-v1:evaluation",
        "shortlist": (evaluation,),
        "scorer": "hybrid",
        "semantic_provider": "openai",
        "semantic_model": "gpt-6-luna",
        "semantic_prompt_version": SEMANTIC_PROMPT_VERSION,
        "semantic_reasoning_effort": "max",
        "semantic_fallback": "heuristic",
    }
    original = scoring_cache_key(**options)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "multicuts.scoring.artifacts.HYBRID_ALGORITHM_VERSION", "hybrid-scoring-v2"
    )
    assert scoring_cache_key(**options) != original  # type: ignore[arg-type]

    monkeypatch.setattr(
        "multicuts.scoring.artifacts.HYBRID_ALGORITHM_VERSION", "hybrid-scoring-v1"
    )
    monkeypatch.setattr(
        "multicuts.scoring.artifacts.HYBRID_FALLBACK_ALGORITHM_VERSION",
        "hybrid-fallback-v2",
    )
    assert scoring_cache_key(**options) != original  # type: ignore[arg-type]


def test_hybrid_cache_rejects_mismatched_persisted_provenance(
    tmp_path: Path,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:semantic")
    config = _config(tmp_path)
    first_scorer = _FakeSemanticScorer(_judgment())
    load_or_score_candidates(
        config,
        source,
        _transcript(),
        _artifact(source),
        semantic_scorer=first_scorer,
    )
    score_path = next(tmp_path.rglob("scores.json"))
    payload = json.loads(score_path.read_text(encoding="utf-8"))
    payload["provenance"]["reasoning_effort"] = "high"
    score_path.write_text(json.dumps(payload), encoding="utf-8")
    replacement = _FakeSemanticScorer(_judgment())

    repaired = load_or_score_candidates(
        config,
        source,
        _transcript(),
        _artifact(source),
        semantic_scorer=replacement,
    )

    assert replacement.calls == 1
    assert repaired.provenance.reasoning_effort == "max"


def test_semantic_score_contract_rejects_false_provenance() -> None:
    hybrid = compose_hybrid_score(_evaluation(), _judgment())

    with pytest.raises(ValueError, match="require semantic provenance"):
        replace(hybrid, provider=None)
    with pytest.raises(ValueError, match="fallback scores"):
        replace(hybrid, scorer="heuristic-fallback")


def test_hybrid_batch_rejects_failure_overlapping_a_semantic_success() -> None:
    hybrid = compose_hybrid_score(_evaluation(), _judgment())
    provenance = ScoringProvenance(
        mode="hybrid",
        provider="openai",
        model="gpt-6-luna",
        prompt_version=SEMANTIC_PROMPT_VERSION,
        reasoning_effort="max",
        fallback="heuristic",
    )
    failure = CandidateScoringFailure(
        candidate_id="candidate-v1:semantic",
        code="timeout",
        warning="Semantic provider request timed out",
        provider="openai",
        model="gpt-6-luna",
        prompt_version=SEMANTIC_PROMPT_VERSION,
        retryable=True,
    )

    with pytest.raises(ValueError, match="overlap only heuristic fallback"):
        ScoringBatch(
            scores=(ScoredCandidate("candidate-v1:semantic", hybrid),),
            failures=(failure,),
            provenance=provenance,
        )


def test_hybrid_batch_requires_configured_fallback_for_each_failure() -> None:
    provenance = ScoringProvenance(
        mode="hybrid",
        provider="openai",
        model="gpt-6-luna",
        prompt_version=SEMANTIC_PROMPT_VERSION,
        reasoning_effort="max",
        fallback="heuristic",
    )
    failure = CandidateScoringFailure(
        candidate_id="candidate-v1:semantic",
        code="timeout",
        warning="Semantic provider request timed out",
        provider="openai",
        model="gpt-6-luna",
        prompt_version=SEMANTIC_PROMPT_VERSION,
        retryable=True,
    )

    with pytest.raises(ValueError, match="each provider failure"):
        ScoringBatch(scores=(), failures=(failure,), provenance=provenance)
