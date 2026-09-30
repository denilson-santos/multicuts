"""Agy CLI structured response adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from multicuts.adapters._llm_common import _json_text, _run_cli
from multicuts.errors import ScoringError


class AgyAdapter:
    def __init__(self, model: str, effort: str | None = None) -> None:
        self.model = model
        self.effort = effort

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        with tempfile.TemporaryDirectory(prefix="multicuts-ai-") as temporary:
            root = Path(temporary)
            schema_path = root / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            raw = _run_cli(
                [
                    "agy",
                    "--print",
                    "--model",
                    self.model,
                    *(["--effort", self.effort] if self.effort is not None else []),
                    "--mode",
                    "plan",
                    "--sandbox",
                    "--output-format",
                    "json",
                    "--json-schema",
                    str(schema_path),
                ],
                prompt,
                cwd=root,
            )
            envelope = _json_text(raw)
            if (
                isinstance(envelope, dict)
                and envelope.get("status") == "SUCCESS"
                and isinstance(envelope.get("structured_output"), dict)
            ):
                return envelope["structured_output"]
            raise ScoringError("agy returned no structured result")
