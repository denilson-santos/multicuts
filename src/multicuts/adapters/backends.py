"""Select the explicitly configured LLM adapter."""

from __future__ import annotations

from multicuts.adapters.agy import AgyAdapter
from multicuts.adapters.anthropic import AnthropicAdapter
from multicuts.adapters.claude import ClaudeAdapter
from multicuts.adapters.codex import CodexAdapter
from multicuts.adapters.gemini import GeminiAdapter
from multicuts.adapters.openai import OpenAIAdapter
from multicuts.errors import ConfigurationError

_BACKENDS = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "codex": CodexAdapter,
    "claude": ClaudeAdapter,
    "agy": AgyAdapter,
}


class LlmBackend:
    def __init__(self, name: str, model: str, effort: str | None = None) -> None:
        try:
            self._backend = _BACKENDS[name](model, effort)
        except KeyError as exc:
            raise ConfigurationError("Unsupported LLM_BACKEND") from exc

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        return self._backend.complete(prompt, schema)
