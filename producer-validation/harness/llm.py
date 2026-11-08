"""Minimal LLM clients (stdlib only). Both arms use the same client/model."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-6", "openai": "gpt-4.1",
                  "github": "openai/gpt-4.1"}
GITHUB_MODELS_URL = "https://models.github.ai/inference"


@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLM:
    def __init__(self, backend: str, model: str | None = None,
                 temperature: float | None = 0.0, max_tokens: int = 16000,
                 responder: Callable[[str, list[dict]], str] | None = None):
        self.backend = backend
        self.model = model or DEFAULT_MODELS.get(backend, backend)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._responder = responder

    def complete(self, system: str, messages: list[dict]) -> Reply:
        if self.backend == "anthropic":
            return self._anthropic(system, messages)
        if self.backend == "openai":
            return self._openai(
                system, messages,
                os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                os.environ.get("OPENAI_API_KEY", ""))
        if self.backend == "github":
            return self._openai(system, messages, GITHUB_MODELS_URL,
                                os.environ.get("GITHUB_TOKEN", ""))
        if self.backend == "mock":
            if self._responder is None:
                raise ValueError("mock backend needs a responder")
            return Reply(self._responder(system, messages))
        raise ValueError(f"unknown backend {self.backend!r}")

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers={"content-type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:2000]
            raise RuntimeError(f"{self.backend} HTTP {exc.code}: {detail}")
        try:
            return json.loads(raw)
        except ValueError:
            raise RuntimeError(f"{self.backend} returned non-JSON response: "
                               f"{raw[:200]!r}")

    def _anthropic(self, system: str, messages: list[dict]) -> Reply:
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "system": system, "messages": messages}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        data = self._post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
             "anthropic-version": "2023-06-01"},
            body,
        )
        text = "".join(b.get("text", "") for b in data["content"])
        usage = data.get("usage", {})
        return Reply(text, usage.get("input_tokens", 0),
                     usage.get("output_tokens", 0))

    def _openai(self, system: str, messages: list[dict], base: str,
                key: str) -> Reply:
        body = {"model": self.model,
                "messages": [{"role": "system", "content": system}, *messages]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        data = self._post(f"{base}/chat/completions",
                          {"authorization": f"Bearer {key}"}, body)
        usage = data.get("usage", {})
        return Reply(data["choices"][0]["message"]["content"],
                     usage.get("prompt_tokens", 0),
                     usage.get("completion_tokens", 0))


def replay_responder(files: dict[str, Path]) -> Callable:
    """Mock responder that always answers with the given files' contents."""
    def respond(system: str, messages: list[dict]) -> str:
        return "\n".join(
            f'<file path="{rel}">\n{path.read_text()}</file>'
            for rel, path in files.items()
        )
    return respond
