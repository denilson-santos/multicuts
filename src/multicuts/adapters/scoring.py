"""OpenAI semantic-scoring boundary with strict normalized output."""

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict
from importlib import import_module
from math import isfinite
from pathlib import Path
from typing import Protocol, cast

from multicuts.errors import ScoringError
from multicuts.models import (
    SCORE_DIMENSIONS,
    ScoreDimension,
    SemanticJudgment,
    SemanticScoringRequest,
)
from multicuts.scoring.semantic import (
    DEFAULT_REASONING_EFFORT,
    DEFAULT_SEMANTIC_MODEL,
    SEMANTIC_PROMPT_VERSION,
    SEMANTIC_PROVIDER,
    SemanticProviderError,
)

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_REASON_LENGTH = 500


def _api_key_from_dotenv() -> str | None:
    try:
        lines = (Path.cwd() / ".env").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ScoringError("Hybrid scoring could not read the .env file") from exc

    for line in lines:
        name, separator, value = line.partition("=")
        if separator and name.strip() == OPENAI_API_KEY_ENV:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None


_INSTRUCTIONS = (
    "Evaluate the candidate as a short standalone clip. Return only the requested "
    "seven 0..100 dimension judgments: hook measures immediate attention; "
    "standalone_context measures independence from surrounding material; payoff "
    "measures the strength of the conclusion or reveal; clarity measures ease of "
    "understanding; emotion_surprise measures emotional or unexpected impact; "
    "quotability measures memorable phrasing; information_density measures useful "
    "content per unit of speech. Return a 0..1 confidence and a concise reason. "
    "Use context only to detect dependencies. Do not produce an overall score or "
    "penalties; those are composed by the application."
)

_STRUCTURED_FORMAT = {
    "type": "json_schema",
    "name": "semantic_clip_judgment",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "dimensions": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    name: {"type": "number", "minimum": 0, "maximum": 100}
                    for name in SCORE_DIMENSIONS
                },
                "required": list(SCORE_DIMENSIONS),
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": ["dimensions", "confidence", "reason"],
    },
}


class _ResponsesClient(Protocol):
    def create(self, **kwargs: object) -> object: ...


class _OpenAIClient(Protocol):
    @property
    def responses(self) -> _ResponsesClient: ...


def _number(value: object, field: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SemanticProviderError(
            "malformed_response",
            f"Semantic provider returned invalid {field}",
            retryable=False,
        )
    number = float(value)
    if not isfinite(number) or not minimum <= number <= maximum:
        raise SemanticProviderError(
            "malformed_response",
            f"Semantic provider returned out-of-range {field}",
            retryable=False,
        )
    return number


def _parse_judgment(
    payload: object, *, provider: str, model: str, prompt_version: str
) -> SemanticJudgment:
    if not isinstance(payload, dict) or set(payload) != {
        "dimensions",
        "confidence",
        "reason",
    }:
        raise SemanticProviderError(
            "malformed_response",
            "Semantic provider returned an invalid response shape",
            retryable=False,
        )
    raw_dimensions = payload["dimensions"]
    if not isinstance(raw_dimensions, dict) or set(raw_dimensions) != set(
        SCORE_DIMENSIONS
    ):
        raise SemanticProviderError(
            "malformed_response",
            "Semantic provider returned invalid score dimensions",
            retryable=False,
        )
    reason = payload["reason"]
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > MAX_REASON_LENGTH
    ):
        raise SemanticProviderError(
            "malformed_response",
            "Semantic provider returned an invalid reason",
            retryable=False,
        )
    try:
        return SemanticJudgment(
            dimensions=tuple(
                ScoreDimension(
                    name,
                    _number(
                        raw_dimensions[name],
                        f"dimension {name}",
                        minimum=0,
                        maximum=100,
                    ),
                )
                for name in SCORE_DIMENSIONS
            ),
            confidence=_number(
                payload["confidence"], "confidence", minimum=0, maximum=1
            ),
            reason=reason.strip(),
            provider=provider,
            model=model,
            prompt_version=prompt_version,
        )
    except ValueError as exc:
        raise SemanticProviderError(
            "malformed_response",
            "Semantic provider returned invalid judgment values",
            retryable=False,
        ) from exc


def _classify_provider_exception(error: Exception) -> SemanticProviderError:
    status = getattr(error, "status_code", None)
    name = type(error).__name__.casefold()
    if "timeout" in name or isinstance(error, TimeoutError):
        return SemanticProviderError(
            "timeout", "Semantic provider request timed out", retryable=True
        )
    if status == 429 or "ratelimit" in name or "rate_limit" in name:
        return SemanticProviderError(
            "rate_limit", "Semantic provider rate limit was reached", retryable=True
        )
    if status in (408, 409) or (isinstance(status, int) and status >= 500):
        return SemanticProviderError(
            "transient_provider",
            "Semantic provider is temporarily unavailable",
            retryable=True,
        )
    if "connection" in name:
        return SemanticProviderError(
            "connection", "Semantic provider connection failed", retryable=True
        )
    if status in (401, 403) or "authentication" in name or "permission" in name:
        return SemanticProviderError(
            "authentication",
            "Semantic provider credentials were rejected",
            retryable=False,
        )
    return SemanticProviderError(
        "provider_error", "Semantic provider request failed", retryable=False
    )


class OpenAISemanticAdapter:
    """Obtain one structured semantic judgment through OpenAI Responses."""

    def __init__(
        self,
        client: _OpenAIClient,
        *,
        model: str = DEFAULT_SEMANTIC_MODEL,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        prompt_version: str = SEMANTIC_PROMPT_VERSION,
        attempts: int = MAX_ATTEMPTS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not model.strip() or not prompt_version.strip():
            raise ValueError("semantic model and prompt version must not be empty")
        if reasoning_effort not in ("none", "low", "medium", "high", "xhigh", "max"):
            raise ValueError("semantic reasoning effort is unsupported")
        if type(attempts) is not int or attempts <= 0:
            raise ValueError("semantic attempts must be positive")
        self._client = client
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.prompt_version = prompt_version
        self._attempts = attempts
        self._sleeper = sleeper

    @classmethod
    def from_environment(
        cls,
        *,
        model: str = DEFAULT_SEMANTIC_MODEL,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    ) -> "OpenAISemanticAdapter":
        api_key = os.environ.get(OPENAI_API_KEY_ENV) or _api_key_from_dotenv()
        if api_key is None or not api_key.strip():
            raise ScoringError(
                "Hybrid scoring requires OPENAI_API_KEY in the environment or .env"
            )
        try:
            module = import_module("openai")
            client_type = vars(module).get("OpenAI")
            if not callable(client_type):
                raise AttributeError("OpenAI client class is unavailable")
        except (ImportError, AttributeError) as exc:
            raise ScoringError(
                "Hybrid scoring requires the optional 'openai' dependency"
            ) from exc
        client = client_type(
            api_key=api_key,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        return cls(
            cast(_OpenAIClient, client), model=model, reasoning_effort=reasoning_effort
        )

    def score(self, request: SemanticScoringRequest) -> SemanticJudgment:
        payload = {
            "candidate_text": request.candidate_text,
            "context_before": request.context_before,
            "context_after": request.context_after,
            "derived_features": asdict(request.features),
        }
        for attempt in range(1, self._attempts + 1):
            try:
                response = self._client.responses.create(
                    model=self.model,
                    reasoning={"effort": self.reasoning_effort},
                    store=False,
                    instructions=_INSTRUCTIONS,
                    input=json.dumps(payload, ensure_ascii=False, allow_nan=False),
                    text={"format": _STRUCTURED_FORMAT},
                )
            except Exception as exc:
                failure = _classify_provider_exception(exc)
                if failure.retryable and attempt < self._attempts:
                    self._sleeper(0.25 * (2 ** (attempt - 1)))
                    continue
                raise failure from exc
            status = getattr(response, "status", None)
            if status is not None and status != "completed":
                raise SemanticProviderError(
                    "incomplete_response",
                    "Semantic provider did not complete the response",
                    retryable=False,
                )
            output = getattr(response, "output_text", None)
            if not isinstance(output, str):
                raise SemanticProviderError(
                    "malformed_response",
                    "Semantic provider returned no structured text",
                    retryable=False,
                )
            try:
                decoded: object = json.loads(output)
            except (TypeError, ValueError) as exc:
                raise SemanticProviderError(
                    "malformed_response",
                    "Semantic provider returned invalid JSON",
                    retryable=False,
                ) from exc
            return _parse_judgment(
                decoded,
                provider=SEMANTIC_PROVIDER,
                model=self.model,
                prompt_version=self.prompt_version,
            )
        raise AssertionError("semantic retry loop exhausted without a result")
