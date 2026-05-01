"""
OpenAI-compatible client — works with OpenAI, Ollama, LM Studio, and any
other server that implements the OpenAI chat completions API.

System prompt handling: OpenAI-compatible APIs carry the system prompt as
a message with role="system" prepended to the conversation, unlike Anthropic
which takes it as a separate parameter.

Structured output: tries response_format=json_schema (supported by OpenAI
and newer Ollama models); falls back to the base-class prompt-injection path
for models that don't support it.
"""

from __future__ import annotations

import json
from typing import Type

from openai import APIConnectionError, NotFoundError, OpenAI
from pydantic import BaseModel

from .base import LLMClient


class OpenAICompatibleClient(LLMClient):

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self._model = model
        # Accept a pre-built client (e.g. constructed by factory for Azure).
        # OpenAI SDK requires a non-empty api_key even for local servers.
        self._client = client or OpenAI(
            base_url=base_url,
            api_key=api_key or "no-key-required",
        )

    def complete(
        self,
        messages: list[dict],
        system: str,
        max_tokens: int = 4096,
    ) -> str:
        full_messages = [{"role": "system", "content": system}, *messages]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=full_messages,
                max_tokens=max_tokens,
            )
        except NotFoundError:
            raise RuntimeError(
                f"Model '{self._model}' not found at {self._client.base_url}. "
                f"For Ollama, run: ollama pull {self._model}"
            )
        except APIConnectionError:
            raise RuntimeError(
                f"Cannot connect to LLM server at {self._client.base_url}. "
                f"For Ollama, ensure it is running: ollama serve"
            )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError(
                f"Model '{self._model}' returned null content. "
                "This usually means a thinking/reasoning model exhausted max_tokens "
                "before generating a response. Try increasing max_tokens."
            )
        return content

    def complete_structured(
        self,
        messages: list[dict],
        system: str,
        response_model: Type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel:
        """Try json_schema response_format; fall back to prompt-based JSON."""
        try:
            full_messages = [{"role": "system", "content": system}, *messages]
            response = self._client.chat.completions.create(
                model=self._model,
                messages=full_messages,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "schema": response_model.model_json_schema(),
                        "strict": False,
                    },
                },
            )
            raw = response.choices[0].message.content
            if raw is None:
                raise ValueError("Model returned null content.")
            data = json.loads(raw)
            return response_model.model_validate(data)
        except (NotFoundError, APIConnectionError):
            raise
        except Exception:
            return super().complete_structured(messages, system, response_model, max_tokens)
