"""
Anthropic SDK implementation of LLMClient.

Prompt caching: complete() detects the "\n\n---\n\n" separator in the
system string and wraps the prefix in a cache_control block automatically.
No caller needs to know about this.

Structured output: complete_structured() uses messages.parse() for reliable
schema-constrained responses; falls back to the base-class JSON path if
parse() is unavailable.
"""

from __future__ import annotations

from typing import Type

import anthropic
from pydantic import BaseModel

from .base import LLMClient

DEFAULT_MODEL = "claude-opus-4-7"
_CACHE_SEP = "\n\n---\n\n"


class AnthropicClient(LLMClient):

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        # api_key=None lets the SDK fall back to ANTHROPIC_API_KEY env var.
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(
        self,
        messages: list[dict],
        system: str,
        max_tokens: int = 4096,
    ) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=self._build_system_param(system),
            messages=messages,
        )
        return response.content[0].text

    def complete_structured(
        self,
        messages: list[dict],
        system: str,
        response_model: Type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel:
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_format=response_model,
            )
            return response.parsed
        except Exception:
            return super().complete_structured(messages, system, response_model, max_tokens)

    def _build_system_param(self, system: str) -> str | list[dict]:
        """Cache the static prefix before the first '---' separator."""
        idx = system.find(_CACHE_SEP)
        if idx <= 0:
            return system
        return [
            {
                "type": "text",
                "text": system[:idx],
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": system[idx + len(_CACHE_SEP):],
            },
        ]
