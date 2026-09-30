"""Anthropic structured response adapter."""

from __future__ import annotations

from multicuts.adapters._llm_common import _json_text, _post, _require_key
from multicuts.errors import ScoringError


def _extract_anthropic(response: dict[str, object]) -> object:
    if response.get("stop_reason") != "end_turn":
        raise ScoringError("Anthropic did not complete the structured response")
    content = response.get("content")
    if isinstance(content, list):
        for item in content:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                return _json_text(item["text"])
    raise ScoringError("Anthropic returned no structured text")


class AnthropicAdapter:
    def __init__(self, model: str, effort: str | None = None) -> None:
        self.model = model
        self.effort = effort

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        output_config: dict[str, object] = {
            "format": {"type": "json_schema", "schema": schema}
        }
        if self.effort is not None:
            output_config["effort"] = self.effort
        response = _post(
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": _require_key("ANTHROPIC_API_KEY"),
                "anthropic-version": "2023-06-01",
            },
            {
                "model": self.model,
                "max_tokens": 16384,
                "messages": [{"role": "user", "content": prompt}],
                "output_config": output_config,
            },
        )
        return _extract_anthropic(response)
