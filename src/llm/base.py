"""
Abstract base class for LLM clients.

All providers implement complete(). complete_structured() has a working
default (inject JSON schema into prompt, parse response) so every provider
gets structured output for free; providers with native support override it.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Type

from pydantic import BaseModel


class LLMClient(ABC):

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        system: str,
        max_tokens: int = 8192,
    ) -> str:
        """Send a chat completion and return the response text."""

    def complete_structured(
        self,
        messages: list[dict],
        system: str,
        response_model: Type[BaseModel],
        max_tokens: int = 8192,
    ) -> BaseModel:
        """
        Request a response that conforms to response_model.

        Default: appends the JSON schema to the system prompt, calls
        complete(), strips markdown fences, and validates with Pydantic.
        Provider subclasses override this when native structured output
        is available (Anthropic messages.parse, OpenAI response_format).
        """
        schema_hint = json.dumps(response_model.model_json_schema(), indent=2)
        augmented_system = (
            f"{system}\n\n"
            "You MUST respond with a single valid JSON object that matches "
            "the schema below exactly. No explanation, no markdown fences — "
            f"raw JSON only:\n{schema_hint}"
        )
        raw = self.complete(messages, augmented_system, max_tokens=max_tokens)
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        data = json.loads(clean)
        return response_model.model_validate(data)
