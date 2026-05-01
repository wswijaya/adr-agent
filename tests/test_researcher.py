"""
Tests for Phase 2: KB loader and researcher utilities.
No live API or search calls — all external interactions are mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from src.kb.loader import KBLoader, _jaccard
from src.llm.mock_client import MockLLMClient
from src.models.adr import Domain
from src.models.state import IntakeResult

FIXTURES = Path(__file__).parent / "fixtures"
KB_DIR = Path(__file__).parent.parent / "src" / "kb"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def streaming_intake() -> IntakeResult:
    data = json.loads((FIXTURES / "intake_result.json").read_text())
    return IntakeResult(**data)


# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------

def test_jaccard_perfect_overlap():
    assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_no_overlap():
    assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_partial():
    # intersection=1, union=3 → 1/3
    result = _jaccard({"a", "b"}, {"b", "c"})
    assert abs(result - 1 / 3) < 1e-9


def test_jaccard_empty_set():
    assert _jaccard(set(), {"a"}) == 0.0
    assert _jaccard({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# KBLoader.load_patterns
# ---------------------------------------------------------------------------

def test_load_patterns_domain_filter():
    loader = KBLoader(KB_DIR)
    options = loader.load_patterns(domain=Domain.DATA_PLATFORM)
    assert len(options) >= 3
    for opt in options:
        assert "name" in opt
        assert opt.get("from_kb") is True


def test_load_patterns_all_domains():
    loader = KBLoader(KB_DIR)
    options = loader.load_patterns()
    # Should include options from all 4 YAML files
    assert len(options) >= 12


def test_load_patterns_unmapped_domain_falls_back_to_all():
    """Domain with no dedicated YAML file falls back to all pattern files."""
    loader = KBLoader(KB_DIR)
    options = loader.load_patterns(domain=Domain.SOLUTION_ARCH)
    # Should still return results — all four YAML files are loaded as fallback
    assert len(options) >= 12


# ---------------------------------------------------------------------------
# KBLoader.keyword_match
# ---------------------------------------------------------------------------

def test_keyword_match_streaming_keywords(streaming_intake):
    loader = KBLoader(KB_DIR)
    options = loader.load_patterns(domain=Domain.DATA_PLATFORM)
    matched = loader.keyword_match(options, streaming_intake.keywords, top_n=5)

    assert len(matched) >= 1
    # Databricks and Iceberg both have "streaming" tag — at least one should appear
    names = [m["name"] for m in matched]
    assert any("Databricks" in n or "Iceberg" in n for n in names)


def test_keyword_match_respects_top_n():
    loader = KBLoader(KB_DIR)
    options = loader.load_patterns()
    matched = loader.keyword_match(options, ["streaming", "kafka", "managed"], top_n=2)
    assert len(matched) <= 2


def test_keyword_match_no_overlap_returns_empty():
    loader = KBLoader(KB_DIR)
    options = loader.load_patterns()
    matched = loader.keyword_match(options, ["quantum", "blockchain", "nanotech"])
    assert matched == []


def test_keyword_match_sorted_by_score():
    loader = KBLoader(KB_DIR)
    options = [
        {"name": "A", "tags": ["kafka", "streaming", "real-time"]},
        {"name": "B", "tags": ["kafka"]},
        {"name": "C", "tags": ["kafka", "streaming"]},
    ]
    matched = loader.keyword_match(options, ["kafka", "streaming", "real-time"], top_n=3)
    names = [m["name"] for m in matched]
    # A has highest Jaccard → should be first
    assert names[0] == "A"


# ---------------------------------------------------------------------------
# KBLoader.load_adr_history
# ---------------------------------------------------------------------------

def test_load_adr_history_empty_dir(tmp_path):
    (tmp_path / "adr_history").mkdir()
    loader = KBLoader(tmp_path)
    assert loader.load_adr_history() == []


def test_load_adr_history_missing_dir(tmp_path):
    loader = KBLoader(tmp_path)
    assert loader.load_adr_history() == []


def test_load_adr_history_parses_options(tmp_path):
    history_dir = tmp_path / "adr_history"
    history_dir.mkdir()

    adr_content = """# ADR-0001: Example Decision

## Options considered

### Option 1: Apache Kafka

Kafka is a distributed event streaming platform designed for high-throughput pipelines.

**Weighted total:** 4.2 / 5.0

---

### Option 2: AWS Kinesis

Kinesis is a serverless streaming service tightly integrated with the AWS ecosystem.

**Weighted total:** 3.5 / 5.0
"""
    (history_dir / "ADR-0001-example.md").write_text(adr_content)

    loader = KBLoader(tmp_path)
    options = loader.load_adr_history()

    assert len(options) == 2
    assert options[0]["name"] == "Apache Kafka"
    assert options[1]["name"] == "AWS Kinesis"
    assert all(o["from_kb"] is True for o in options)
    assert all(o["source"] == "ADR-0001-example.md" for o in options)


# ---------------------------------------------------------------------------
# build_search_queries
# ---------------------------------------------------------------------------

def test_build_search_queries_returns_list(streaming_intake):
    from src.agent.researcher import build_search_queries

    queries = build_search_queries(MockLLMClient(), streaming_intake, num_queries=5)

    assert isinstance(queries, list)
    assert 1 <= len(queries) <= 5
    assert all(isinstance(q, str) for q in queries)


def test_build_search_queries_fallback_on_bad_json(streaming_intake):
    """If LLM returns non-JSON, fall back to raw keywords."""
    from src.agent.researcher import build_search_queries
    from src.llm.base import LLMClient

    class BadJsonClient(LLMClient):
        def complete(self, messages, system, max_tokens=4096):
            return "Sorry, I cannot help with that."

    queries = build_search_queries(BadJsonClient(), streaming_intake, num_queries=3)
    assert queries == streaming_intake.keywords[:3]


# ---------------------------------------------------------------------------
# run_web_search
# ---------------------------------------------------------------------------

def test_run_web_search_calls_client():
    from src.agent.researcher import run_web_search

    mock_client = MagicMock()
    mock_client.search.return_value = [
        {"title": "Result", "url": "https://example.com", "snippet": "Test snippet"}
    ]

    results = run_web_search(["query one", "query two"], mock_client)

    assert mock_client.search.call_count == 2
    assert len(results) == 2
    assert all("query" in r and "results" in r for r in results)


def test_run_web_search_handles_failure_gracefully():
    from src.agent.researcher import run_web_search

    mock_client = MagicMock()
    mock_client.search.side_effect = RuntimeError("Network timeout")

    results = run_web_search(["query"], mock_client)

    assert len(results) == 1
    assert results[0]["results"] == []


# ---------------------------------------------------------------------------
# _resolve_search_client
# ---------------------------------------------------------------------------

def test_resolve_search_client_explicit_passthrough():
    from src.agent.orchestrator import _resolve_search_client

    mock = MagicMock()
    assert _resolve_search_client(mock) is mock


def test_resolve_search_client_none_when_no_env(monkeypatch):
    from src.agent.orchestrator import _resolve_search_client

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)

    assert _resolve_search_client(None) is None


def test_resolve_search_client_tavily_from_env(monkeypatch):
    from src.agent.orchestrator import _resolve_search_client
    from src.agent.researcher import TavilySearchClient

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)

    client = _resolve_search_client(None)
    assert isinstance(client, TavilySearchClient)


def test_resolve_search_client_duckduckgo_from_env(monkeypatch):
    from src.agent.orchestrator import _resolve_search_client
    from src.agent.researcher import DuckDuckGoSearchClient

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "duckduckgo")

    client = _resolve_search_client(None)
    assert isinstance(client, DuckDuckGoSearchClient)
