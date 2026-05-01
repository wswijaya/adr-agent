"""
researcher.py — Web search clients and query generation for the research phase.

WebSearchClient is a Protocol — any object with a .search() method works.
Four built-in implementations:
  - TavilySearchClient        (TAVILY_API_KEY)
  - FirecrawlSearchClient     (FIRECRAWL_API_KEY)
  - DuckDuckGoSearchClient    (no API key required)
  - AnthropicWebSearchClient  (ANTHROPIC_API_KEY, uses claude web_search tool)

build_search_queries() uses the LLM to generate targeted queries from the intake.
run_web_search() executes queries concurrently via ThreadPoolExecutor.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol, runtime_checkable

from rich.console import Console

from ..llm.base import LLMClient
from ..models.state import IntakeResult
from . import prompts

console = Console()


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class WebSearchClient(Protocol):
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Return a list of {title, url, snippet} dicts."""
        ...


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

class TavilySearchClient:
    """Wraps the Tavily search API. Requires TAVILY_API_KEY."""

    def __init__(self, api_key: str) -> None:
        from tavily import TavilyClient
        self._client = TavilyClient(api_key=api_key)

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        response = self._client.search(query=query, max_results=max_results)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in response.get("results", [])
        ]


class FirecrawlSearchClient:
    """
    Uses the Firecrawl search API. Requires FIRECRAWL_API_KEY.
    Returns richer content than Tavily — Firecrawl scrapes and cleans pages.
    """

    def __init__(self, api_key: str) -> None:
        from firecrawl import FirecrawlApp
        self._client = FirecrawlApp(api_key=api_key)

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        response = self._client.search(query, params={"limit": max_results})
        results = []
        # FirecrawlApp.search() returns a SearchResponse with a .data list
        items = response.data if hasattr(response, "data") else (response if isinstance(response, list) else [])
        for item in items:
            # Each item may be a dict or an object with attributes
            if isinstance(item, dict):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", item.get("markdown", ""))[:400],
                })
            else:
                results.append({
                    "title": getattr(item, "title", ""),
                    "url": getattr(item, "url", ""),
                    "snippet": (getattr(item, "description", None) or getattr(item, "markdown", ""))[:400],
                })
        return results


class DuckDuckGoSearchClient:
    """
    Uses the ddgs library. No API key required.
    Rate-limited by DuckDuckGo — suitable for low-volume usage and local dev.
    """

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return results


class AnthropicWebSearchClient:
    """
    Uses Claude's built-in web_search tool. Requires ANTHROPIC_API_KEY.
    Uses a smaller model to keep search costs low.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": f"Search for: {query}"}],
        )
        results: list[dict] = []
        for block in response.content:
            for citation in getattr(block, "citations", []):
                results.append({
                    "title": getattr(citation, "title", ""),
                    "url": getattr(citation, "url", ""),
                    "snippet": getattr(citation, "cited_text", "")[:300],
                })
        return results[:max_results]


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------

def build_search_queries(
    client: LLMClient,
    intake: IntakeResult,
    num_queries: int = 5,
) -> list[str]:
    """
    Ask the LLM to generate targeted web search queries from the problem intake.
    Falls back to raw intake keywords if the LLM response cannot be parsed.
    """
    user_msg = prompts.QUERY_GENERATION_USER_TEMPLATE.format(
        intake_json=intake.model_dump_json(indent=2),
        num_queries=num_queries,
    )
    raw = client.complete(
        messages=[{"role": "user", "content": user_msg}],
        system=prompts.QUERY_GENERATION_SYSTEM,
        max_tokens=512,
    )
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        queries = json.loads(clean)
        if isinstance(queries, list) and queries:
            return [str(q) for q in queries[:num_queries]]
    except (json.JSONDecodeError, ValueError):
        pass
    return intake.keywords[:num_queries]


# ---------------------------------------------------------------------------
# Concurrent execution
# ---------------------------------------------------------------------------

def run_web_search(
    queries: list[str],
    search_client: WebSearchClient,
    max_results_per_query: int = 5,
    max_workers: int = 5,
    per_query_timeout: float = 10.0,
) -> list[dict]:
    """
    Execute queries concurrently. Returns [{query, results: [{title, url, snippet}]}].
    Search failures are caught per-query and logged as warnings.
    """
    output: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_query = {
            pool.submit(search_client.search, q, max_results_per_query): q
            for q in queries
        }
        for future in as_completed(future_to_query):
            query = future_to_query[future]
            try:
                results = future.result(timeout=per_query_timeout)
                output.append({"query": query, "results": results})
            except Exception as exc:
                console.print(f"  [yellow]Search failed for '{query}': {exc}[/yellow]")
                output.append({"query": query, "results": []})

    return output
