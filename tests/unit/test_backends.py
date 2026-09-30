"""Hermetic structured-output contracts for all selectable AI backends."""

import importlib
import json
from pathlib import Path

import pytest

from multicuts.adapters import backends

_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {"type": "string"}}},
    "required": ["clips"],
}


@pytest.mark.parametrize("backend", ["openai", "anthropic", "gemini"])
@pytest.mark.parametrize("effort", [None, "high"])
def test_api_backends_request_schema_and_extract_json(
    backend: str, effort: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    requests = []

    def post(url: str, headers: dict[str, str], payload: dict[str, object]):
        requests.append((url, headers, payload))
        if backend == "openai":
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"clips":[]}'}],
                    }
                ],
            }
        if backend == "anthropic":
            return {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"clips":[]}'}],
            }
        return {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"clips":[]}'}]},
                }
            ]
        }

    provider = importlib.import_module(f"multicuts.adapters.{backend}")
    monkeypatch.setattr(provider, "_post", post)
    assert backends.LlmBackend(backend, "test-model", effort).complete(
        "prompt", _SCHEMA
    ) == {"clips": []}
    assert len(requests) == 1
    url, headers, payload = requests[0]
    assert "test-model" in (str(payload) + url)
    assert "test-key" in str(headers)
    assert "prompt" in str(payload)
    if backend == "openai":
        assert payload.get("reasoning") == ({"effort": effort} if effort else None)
        assert payload["text"] == {
            "format": {
                "type": "json_schema",
                "name": "multicuts_result",
                "strict": True,
                "schema": _SCHEMA,
            }
        }
    elif backend == "anthropic":
        assert payload["output_config"] == {
            "format": {"type": "json_schema", "schema": _SCHEMA},
            **({"effort": effort} if effort else {}),
        }
    else:
        assert payload["generationConfig"] == {
            "responseMimeType": "application/json",
            "responseJsonSchema": _SCHEMA,
            **({"thinkingConfig": {"thinkingLevel": effort}} if effort else {}),
        }


@pytest.mark.parametrize("backend", ["codex", "claude", "agy"])
@pytest.mark.parametrize("effort", [None, "high"])
def test_cli_backends_use_noninteractive_structured_output(
    backend: str, effort: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = []

    def run_cli(command: list[str], prompt: str, *, cwd: Path) -> str:
        commands.append((command, prompt, cwd))
        assert cwd.is_dir()
        if backend == "codex":
            target = Path(command[command.index("--output-last-message") + 1])
            target.write_text('{"clips":[]}', encoding="utf-8")
            return ""
        return json.dumps({"status": "SUCCESS", "structured_output": {"clips": []}})

    provider = importlib.import_module(f"multicuts.adapters.{backend}")
    monkeypatch.setattr(provider, "_run_cli", run_cli)
    assert backends.LlmBackend(backend, "test-model", effort).complete(
        "prompt", _SCHEMA
    ) == {"clips": []}
    assert len(commands) == 1
    command, prompt, _cwd = commands[0]
    assert command[0] == backend
    assert "test-model" in command
    assert prompt == "prompt"
    assert "--json-schema" in command or "--output-schema" in command
    if backend == "codex":
        assert "read-only" in command
        assert ("--config" in command) == (effort is not None)
        if effort is not None:
            assert (
                command[command.index("--config") + 1]
                == 'model_reasoning_effort="high"'
            )
    elif backend == "agy":
        assert "plan" in command
    else:
        assert "--tools" in command and command[command.index("--tools") + 1] == ""
    if backend != "codex":
        assert ("--effort" in command) == (effort is not None)
        if effort is not None:
            assert command[command.index("--effort") + 1] == effort
