"""Openai structured response adapter."""

from __future__ import annotations

from multicuts.adapters._llm_common import _json_text, _post, _require_key
from multicuts.errors import ScoringError


def _extract_openai(response: dict[str, object]) -> object:
    if response.get("status") != "completed":
        raise ScoringError("OpenAI did not complete the structured response")
    output = response.get("output")
    if not isinstance(output, list):
        raise ScoringError("OpenAI returned no output")
    for message in output:
        if not isinstance(message, dict) or message.get("type") != "message":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if (
                isinstance(item, dict)
                and item.get("type") == "output_text"
                and isinstance(item.get("text"), str)
            ):
                return _json_text(item["text"])
    raise ScoringError("OpenAI returned no structured text")


class OpenAIAdapter:
    def __init__(self, model: str, effort: str | None = None) -> None:
        self.model = model
        self.effort = effort

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        payload: dict[str, object] = {
            "model": self.model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "multicuts_result",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        if self.effort is not None:
            payload["reasoning"] = {"effort": self.effort}
        response = _post(
            "https://api.openai.com/v1/responses",
            {"Authorization": f"Bearer {_require_key('OPENAI_API_KEY')}"},
            payload,
        )
        return _extract_openai(response)
