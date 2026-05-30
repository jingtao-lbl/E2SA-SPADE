"""LLM client wrapper for LitReviewAgent's Phase 5b orchestration.

Defines an abstract LLM Protocol and a concrete AnthropicLLM implementation
backed by the official anthropic SDK. A FakeLLM is also provided for tests
so the modules that depend on LLM calls can be exercised offline.

API key is loaded from the ANTHROPIC_API_KEY environment variable, or
optionally from `~/.claude/.env` if present (matching Jing's existing key
storage convention).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


def _load_api_key() -> str | None:
    """Try environment, then ~/.claude/.env, for ANTHROPIC_API_KEY."""
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key

    dotenv = Path.home() / ".claude" / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "ANTHROPIC_API_KEY":
                return value
    return None


class LLM(Protocol):
    """Minimal LLM interface used by Phase 5b modules."""

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        """Return the model's response to a system + user prompt."""
        ...


class AnthropicLLM:
    """Anthropic Claude wrapper. Uses prompt caching where supported.

    Default model is claude-sonnet-4-6 (latest Sonnet 4.6). Override via
    the model parameter or the ANTHROPIC_MODEL environment variable.
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        from anthropic import Anthropic

        resolved_key = api_key or _load_api_key()
        if not resolved_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not found. Set it in the environment "
                "or in ~/.claude/.env"
            )
        self.client = Anthropic(api_key=resolved_key)
        self.model = (
            model
            or os.environ.get("ANTHROPIC_MODEL")
            or "claude-sonnet-4-5"
        )

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Concatenate all text blocks
        parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)


class FakeLLM:
    """Deterministic fake for tests. Returns canned responses in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.call_log: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        self.call_log.append((system, user))
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted: no more canned responses")
        return self._responses.pop(0)
