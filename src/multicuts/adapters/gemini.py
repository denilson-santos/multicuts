"""Gemini structured response adapter."""

from __future__ import annotations

from urllib.parse import quote

from multicuts.adapters._llm_common import _json_text, _post, _require_key
from multicuts.errors import ConfigurationError, ScoringError


def _extract_gemini(response: dict[str, object]) -> object:
    candidates = response.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0]
        if isinstance(first, dict) and first.get("finishReason") == "STOP":
            content = first.get("content")
            if isinstance(content, dict) and isinstance(content.get("parts"), list):
                for part in content["parts"]:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        return _json_text(part["text"])
    raise ScoringError("Gemini returned no complete structured response")


class GeminiAdapter:
    def __init__(self, model: str, effort: str | None = None) -> None:
        self.model = model
        self.effort = effort

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        if self.effort is not None and self.model.startswith("gemini-2.5-"):
            raise ConfigurationError(
                "Gemini 2.5 uses a thinking budget; omit LLM_EFFORT or choose Gemini 3"
            )
        generation_config: dict[str, object] = {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        }
        if self.effort is not None:
            generation_config["thinkingConfig"] = {"thinkingLevel": self.effort}
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + quote(self.model, safe="")
            + ":generateContent"
        )
        response = _post(
            endpoint,
            {"x-goog-api-key": _require_key("GEMINI_API_KEY")},
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": generation_config,
            },
        )
        return _extract_gemini(response)
