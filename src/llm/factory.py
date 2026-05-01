"""
Factory for creating LLMClient instances from environment configuration.

Environment variables (all optional):
  LLM_PROVIDER             — anthropic | openai | ollama | azure  (default: anthropic)
  LLM_MODEL                — model/deployment name for the chosen provider
  LLM_BASE_URL             — API base URL (required for ollama if non-default port/host)
  LLM_API_KEY              — API key; anthropic provider also accepts ANTHROPIC_API_KEY
  AZURE_OPENAI_ENDPOINT    — required when LLM_PROVIDER=azure

Adding a new provider:
  1. Create src/llm/<name>_client.py implementing LLMClient.
  2. Add one elif branch below.
  3. Set LLM_PROVIDER=<name> in .env.
"""

from __future__ import annotations

import os

from .base import LLMClient

_DEFAULTS: dict[str, dict] = {
    "anthropic": {"model": "claude-opus-4-7"},
    "openai":    {"model": "gpt-4o",    "base_url": "https://api.openai.com/v1"},
    "ollama":    {"model": "llama3.2",  "base_url": "http://localhost:11434/v1"},
    "azure":     {"model": "gpt-4o"},
}

_VALID_PROVIDERS = tuple(_DEFAULTS)


def create_llm_client(
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LLMClient:
    """Return an LLMClient for the configured provider."""
    provider = (provider or os.getenv("LLM_PROVIDER", "anthropic")).lower()
    model    = model    or os.getenv("LLM_MODEL")
    base_url = base_url or os.getenv("LLM_BASE_URL")
    api_key  = api_key  or os.getenv("LLM_API_KEY")

    if provider not in _VALID_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            f"Valid options: {', '.join(_VALID_PROVIDERS)}"
        )

    defaults = _DEFAULTS[provider]

    if provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            model=model or defaults["model"],
        )

    if provider in ("openai", "ollama"):
        from .openai_compatible_client import OpenAICompatibleClient
        return OpenAICompatibleClient(
            model=model or defaults["model"],
            base_url=base_url or defaults["base_url"],
            api_key=api_key,
        )

    if provider == "azure":
        from openai import OpenAI
        from .openai_compatible_client import OpenAICompatibleClient
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or base_url
        if not endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT is required when LLM_PROVIDER=azure. "
                "Set it to your resource URL, e.g. https://<resource>.openai.azure.com/"
            )
        if not api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=azure.")
        deployment = model or defaults["model"]
        _client = OpenAI(base_url=endpoint, api_key=api_key)
        return OpenAICompatibleClient(model=deployment, client=_client)
