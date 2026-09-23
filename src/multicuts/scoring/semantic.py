"""Project-owned semantic scoring request boundary and limited text context."""

from typing import Protocol

from multicuts.models import (
    CandidateEvaluation,
    SemanticJudgment,
    SemanticScoringRequest,
    Transcript,
)

SEMANTIC_PROVIDER = "openai"
DEFAULT_SEMANTIC_MODEL = "gpt-6-luna"
DEFAULT_REASONING_EFFORT = "max"
SEMANTIC_PROMPT_VERSION = "semantic-score-v1"
CONTEXT_CHARACTER_LIMIT = 500


class SemanticProviderError(Exception):
    """A safely classified semantic-provider failure."""

    def __init__(self, code: str, warning: str, *, retryable: bool) -> None:
        super().__init__(warning)
        self.code = code
        self.warning = warning
        self.retryable = retryable


class SemanticScorer(Protocol):
    """The substitutable external semantic-judgment boundary."""

    def score(self, request: SemanticScoringRequest) -> SemanticJudgment: ...


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def build_semantic_request(
    evaluation: CandidateEvaluation,
    transcript: Transcript,
    *,
    context_limit: int = CONTEXT_CHARACTER_LIMIT,
) -> SemanticScoringRequest:
    """Build bounded context from observed transcript timing."""
    if evaluation.hard_failed or evaluation.shortlist_rank is None:
        raise ValueError("only shortlisted eligible candidates may be scored")
    if type(context_limit) is not int or context_limit < 0:
        raise ValueError("semantic context limit must be non-negative")

    candidate = evaluation.candidate
    timed_text = [
        (segment.text, segment.start, segment.end)
        for segment in transcript.segments
        if segment.start is not None and segment.end is not None
    ]
    if not timed_text:
        timed_text = [
            (word.text, word.start, word.end)
            for word in transcript.words
            if word.start is not None and word.end is not None
        ]
    preceding = [
        _normalized_text(text) for text, _, end in timed_text if end <= candidate.start
    ]
    following = [
        _normalized_text(text)
        for text, start, _ in timed_text
        if start >= candidate.end
    ]
    before = _normalized_text(" ".join(preceding))
    after = _normalized_text(" ".join(following))
    if context_limit == 0:
        before = after = ""
    else:
        before = before[-context_limit:]
        after = after[:context_limit]
    return SemanticScoringRequest(
        candidate_id=candidate.candidate_id,
        candidate_text=_normalized_text(candidate.text),
        context_before=before,
        context_after=after,
        features=evaluation.features,
    )
