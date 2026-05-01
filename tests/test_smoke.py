"""
Smoke test: runs the SCORE and WRITE phases using fixture data and a mock
LLM client. No live API calls are made.

The canonical test case is a streaming platform decision (10M events/day).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.llm.mock_client import MockLLMClient
from src.models.adr import Confidence, Domain
from src.models.state import AgentPhase, AgentState, IntakeResult, ResearchResult

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG_DIR = Path(__file__).parent.parent / "config"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def intake() -> IntakeResult:
    data = json.loads((FIXTURES / "intake_result.json").read_text())
    return IntakeResult(**data)


@pytest.fixture
def research_results() -> list[ResearchResult]:
    data = json.loads((FIXTURES / "research_results.json").read_text())
    return [ResearchResult(**r) for r in data]


@pytest.fixture
def populated_state(intake, research_results) -> AgentState:
    state = AgentState(raw_input=intake.problem_statement)
    state.intake = intake
    state.research_results = research_results
    state.phase = AgentPhase.SCORE
    return state


@pytest.fixture
def rubric() -> dict:
    import yaml
    return yaml.safe_load((CONFIG_DIR / "rubric.yaml").read_text())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_rubric_weights_sum_to_one(rubric):
    total = sum(d["weight"] for d in rubric["dimensions"])
    assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"


def test_rubric_has_required_keys(rubric):
    assert "dimensions" in rubric
    assert "confidence" in rubric
    assert "retry" in rubric
    for dim in rubric["dimensions"]:
        assert "id" in dim
        assert "weight" in dim


def test_scoring_phase(populated_state, rubric):
    from src.agent.orchestrator import run_scoring

    state = run_scoring(populated_state, MockLLMClient(), rubric)

    assert state.phase == AgentPhase.CONFIDENCE_CHECK
    assert len(state.scored_options) == 2
    for opt in state.scored_options:
        assert 1.0 <= opt.weighted_total <= 5.0
        assert len(opt.dimension_scores) == 6


def test_weighted_total_calculation(rubric):
    from src.agent.scorer import compute_weighted_total as _compute_weighted_total
    from src.models.adr import Confidence, DimensionScore

    scores = [
        DimensionScore(dimension_id="fit",         label="l", score=4, confidence=Confidence.HIGH,   rationale="r"),
        DimensionScore(dimension_id="maturity",    label="l", score=3, confidence=Confidence.HIGH,   rationale="r"),
        DimensionScore(dimension_id="cost",        label="l", score=3, confidence=Confidence.MEDIUM, rationale="r"),
        DimensionScore(dimension_id="ops",         label="l", score=4, confidence=Confidence.HIGH,   rationale="r"),
        DimensionScore(dimension_id="risk",        label="l", score=4, confidence=Confidence.HIGH,   rationale="r"),
        DimensionScore(dimension_id="skill_match", label="l", score=3, confidence=Confidence.MEDIUM, rationale="r"),
    ]
    # 4×0.25 + 3×0.20 + 3×0.15 + 4×0.15 + 4×0.15 + 3×0.10
    # = 1.00 + 0.60 + 0.45 + 0.60 + 0.60 + 0.30 = 3.55
    result = _compute_weighted_total(scores, rubric)
    assert result == 3.55


def test_write_phase_dry_run(populated_state, rubric, tmp_path):
    from src.agent.orchestrator import run_scoring, run_write

    state = run_scoring(populated_state, MockLLMClient(), rubric)
    state.phase = AgentPhase.WRITE
    state.dry_run = True

    state, out_path = run_write(state, MockLLMClient(), tmp_path, rubric)

    assert state.phase == AgentPhase.DONE
    assert re.match(r"ADR-\d{4}-.+\.md", out_path.name)


def test_write_phase_creates_file(populated_state, rubric, tmp_path):
    from src.agent.orchestrator import run_scoring, run_write

    state = run_scoring(populated_state, MockLLMClient(), rubric)
    state.phase = AgentPhase.WRITE

    state, out_path = run_write(state, MockLLMClient(), tmp_path, rubric)

    assert state.phase == AgentPhase.DONE
    assert out_path.exists()
    assert "ADR" in out_path.read_text()


def test_llm_factory_default_provider():
    import os
    from unittest.mock import patch
    from src.llm.factory import create_llm_client
    from src.llm.anthropic_client import AnthropicClient

    with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"}, clear=False):
        client = create_llm_client(api_key="test-key")
        assert isinstance(client, AnthropicClient)


def test_llm_factory_ollama():
    from src.llm.factory import create_llm_client
    from src.llm.openai_compatible_client import OpenAICompatibleClient

    client = create_llm_client(provider="ollama")
    assert isinstance(client, OpenAICompatibleClient)


def test_llm_factory_invalid_provider():
    from src.llm.factory import create_llm_client

    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_llm_client(provider="unknown-provider")


def test_demo_full_pipeline(rubric, tmp_path):
    """Demo command path: full pipeline from INTAKE through WRITE using MockLLMClient."""
    from src.agent.orchestrator import run as orchestrator_run
    from src.llm.mock_client import DEMO_PROBLEM, DEMO_STAKEHOLDERS

    kb_dir = Path(__file__).parent.parent / "src" / "kb"
    config_dir = Path(__file__).parent.parent / "config"

    out_path = orchestrator_run(
        problem_statement=DEMO_PROBLEM,
        decisions_dir=tmp_path,
        kb_dir=kb_dir,
        config_dir=config_dir,
        llm_client=MockLLMClient(),
        stakeholders=DEMO_STAKEHOLDERS,
        dry_run=False,
    )

    assert out_path.exists()
    assert re.match(r"ADR-\d{4}-.+\.md", out_path.name)
    content = out_path.read_text()
    assert "Confluent" in content
