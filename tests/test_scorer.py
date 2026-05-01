"""
Tests for Phase 3: scorer module.
No live API calls — MockLLMClient and fixture JSON throughout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.agent.scorer import (
    check_confidence,
    compute_weighted_total,
    score_all_options,
    score_option,
    suggest_retry_queries,
)
from src.llm.mock_client import MockLLMClient
from src.models.adr import Confidence, DimensionScore, Option
from src.models.state import IntakeResult, ResearchResult

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG_DIR = Path(__file__).parent.parent / "config"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rubric() -> dict:
    return yaml.safe_load((CONFIG_DIR / "rubric.yaml").read_text())


@pytest.fixture
def intake() -> IntakeResult:
    data = json.loads((FIXTURES / "intake_result.json").read_text())
    return IntakeResult(**data)


@pytest.fixture
def kafka_result() -> ResearchResult:
    return ResearchResult(
        option_name="Apache Kafka on Confluent Cloud",
        summary="Fully managed Kafka with Schema Registry.",
        evidence=["99.99% SLA", "Schema Registry included"],
        sources=["https://docs.confluent.io/"],
    )


@pytest.fixture
def kinesis_result() -> ResearchResult:
    return ResearchResult(
        option_name="AWS Kinesis Data Streams",
        summary="Serverless AWS streaming with on-demand scaling.",
        evidence=["Auto-scales without shard management"],
        sources=["https://docs.aws.amazon.com/streams/latest/dev/introduction.html"],
    )


def _make_option(name: str, scores: list[int], confidences: list[Confidence], rubric: dict) -> Option:
    dim_ids = ["fit", "maturity", "cost", "ops", "risk", "skill_match"]
    dim_scores = [
        DimensionScore(dimension_id=dim_ids[i], label=dim_ids[i], score=s, confidence=c, rationale="r")
        for i, (s, c) in enumerate(zip(scores, confidences))
    ]
    return Option(
        name=name,
        summary="summary",
        dimension_scores=dim_scores,
        weighted_total=compute_weighted_total(dim_scores, rubric),
    )


# ---------------------------------------------------------------------------
# compute_weighted_total
# ---------------------------------------------------------------------------

def test_compute_weighted_total_known_values(rubric):
    scores = [
        DimensionScore(dimension_id="fit",         label="l", score=4, confidence=Confidence.HIGH,   rationale="r"),
        DimensionScore(dimension_id="maturity",    label="l", score=3, confidence=Confidence.HIGH,   rationale="r"),
        DimensionScore(dimension_id="cost",        label="l", score=3, confidence=Confidence.MEDIUM, rationale="r"),
        DimensionScore(dimension_id="ops",         label="l", score=4, confidence=Confidence.HIGH,   rationale="r"),
        DimensionScore(dimension_id="risk",        label="l", score=4, confidence=Confidence.HIGH,   rationale="r"),
        DimensionScore(dimension_id="skill_match", label="l", score=3, confidence=Confidence.MEDIUM, rationale="r"),
    ]
    # 4×0.25 + 3×0.20 + 3×0.15 + 4×0.15 + 4×0.15 + 3×0.10 = 3.55
    assert compute_weighted_total(scores, rubric) == 3.55


def test_compute_weighted_total_all_fives(rubric):
    scores = [
        DimensionScore(dimension_id=d["id"], label=d["id"], score=5, confidence=Confidence.HIGH, rationale="r")
        for d in rubric["dimensions"]
    ]
    assert compute_weighted_total(scores, rubric) == 5.0


def test_compute_weighted_total_all_ones(rubric):
    scores = [
        DimensionScore(dimension_id=d["id"], label=d["id"], score=1, confidence=Confidence.LOW, rationale="r")
        for d in rubric["dimensions"]
    ]
    assert compute_weighted_total(scores, rubric) == 1.0


# ---------------------------------------------------------------------------
# check_confidence
# ---------------------------------------------------------------------------

def test_check_confidence_all_high(rubric):
    opt = _make_option("A", [4, 4, 4, 4, 4, 4], [Confidence.HIGH] * 6, rubric)
    assert check_confidence([opt], threshold=2) == []


def test_check_confidence_exactly_at_threshold(rubric):
    confs = [Confidence.LOW, Confidence.LOW, Confidence.HIGH, Confidence.HIGH, Confidence.HIGH, Confidence.HIGH]
    opt = _make_option("A", [3, 3, 3, 3, 3, 3], confs, rubric)
    assert check_confidence([opt], threshold=2) == ["A"]


def test_check_confidence_below_threshold(rubric):
    confs = [Confidence.LOW, Confidence.HIGH, Confidence.HIGH, Confidence.HIGH, Confidence.HIGH, Confidence.HIGH]
    opt = _make_option("A", [3, 3, 3, 3, 3, 3], confs, rubric)
    assert check_confidence([opt], threshold=2) == []


def test_check_confidence_multiple_options(rubric):
    good = _make_option("Good", [4, 4, 4, 4, 4, 4], [Confidence.HIGH] * 6, rubric)
    weak = _make_option("Weak", [2, 2, 2, 2, 2, 2], [Confidence.LOW] * 6, rubric)
    result = check_confidence([good, weak], threshold=2)
    assert result == ["Weak"]


# ---------------------------------------------------------------------------
# score_option
# ---------------------------------------------------------------------------

def test_score_option_returns_valid_option(intake, kafka_result, rubric):
    option = score_option(MockLLMClient(), intake, kafka_result, rubric)

    assert option.name == "Apache Kafka on Confluent Cloud"
    assert 1.0 <= option.weighted_total <= 5.0
    assert len(option.dimension_scores) == 6
    assert all(1 <= ds.score <= 5 for ds in option.dimension_scores)
    assert all(ds.confidence in list(Confidence) for ds in option.dimension_scores)


def test_score_option_json_retry_on_bad_response(intake, kafka_result, rubric):
    """LLM returns bad JSON on first call, valid JSON on second."""
    from src.llm.base import LLMClient

    call_count = 0
    good_response = json.dumps(json.loads((FIXTURES / "scoring_response_kafka.json").read_text()))

    class FlakyClient(LLMClient):
        def complete(self, messages, system, max_tokens=4096):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "not valid json at all"
            return good_response

    option = score_option(FlakyClient(), intake, kafka_result, rubric)
    assert call_count == 2
    assert option.name == "Apache Kafka on Confluent Cloud"


def test_score_option_raises_after_two_bad_responses(intake, kafka_result, rubric):
    from src.llm.base import LLMClient

    class AlwaysBadClient(LLMClient):
        def complete(self, messages, system, max_tokens=4096):
            return "{ this is not json }"

    with pytest.raises(ValueError, match="invalid JSON after retry"):
        score_option(AlwaysBadClient(), intake, kafka_result, rubric)


# ---------------------------------------------------------------------------
# score_all_options
# ---------------------------------------------------------------------------

def test_score_all_options_sorted_descending(intake, kafka_result, kinesis_result, rubric):
    options = score_all_options(MockLLMClient(), intake, [kafka_result, kinesis_result], rubric)

    assert len(options) == 2
    assert options[0].weighted_total >= options[1].weighted_total


def test_score_all_options_empty_input(intake, rubric):
    options = score_all_options(MockLLMClient(), intake, [], rubric)
    assert options == []


# ---------------------------------------------------------------------------
# suggest_retry_queries
# ---------------------------------------------------------------------------

def test_suggest_retry_queries_returns_list(intake, rubric):
    weak = [_make_option("Weak", [2, 2, 2, 2, 2, 2], [Confidence.LOW] * 6, rubric)]
    queries = suggest_retry_queries(MockLLMClient(), intake, weak)

    assert isinstance(queries, list)


def test_suggest_retry_queries_empty_on_bad_json(intake, rubric):
    from src.llm.base import LLMClient

    class BadClient(LLMClient):
        def complete(self, messages, system, max_tokens=4096):
            return "not json"

    weak = [_make_option("Weak", [2, 2, 2, 2, 2, 2], [Confidence.LOW] * 6, rubric)]
    queries = suggest_retry_queries(BadClient(), intake, weak)
    assert queries == []


# ---------------------------------------------------------------------------
# Retry loop integration
# ---------------------------------------------------------------------------

def test_retry_loop_preserves_strong_options(intake, rubric, tmp_path):
    """
    Simulate a retry: strong option keeps its score across the retry pass.
    The retry researches only the weak option, then merges scores.
    """
    from src.agent.orchestrator import run_confidence_check, run_scoring
    from src.models.state import AgentPhase, AgentState, ResearchResult

    # Build one strong and one weak research result
    strong_result = ResearchResult(option_name="Strong Option", summary="good", evidence=[], sources=[])
    weak_result = ResearchResult(option_name="Weak Option", summary="uncertain", evidence=[], sources=[])

    state = AgentState(raw_input="test", max_retries=2)
    state.intake = intake
    state.research_results = [strong_result, weak_result]
    state.phase = AgentPhase.SCORE

    # First scoring pass — MockLLMClient gives high-confidence scores for both
    state = run_scoring(state, MockLLMClient(), rubric)
    assert len(state.scored_options) == 2

    # Manually inject LOW confidence into the weak option to force retry
    from src.models.adr import DimensionScore
    weak_option = next(o for o in state.scored_options if o.name == "Weak Option")
    for ds in weak_option.dimension_scores:
        object.__setattr__(ds, "confidence", Confidence.LOW)

    strong_count_before = sum(1 for o in state.scored_options if o.name == "Strong Option")

    state = run_confidence_check(state, MockLLMClient(), tmp_path, rubric)

    # Strong option should be preserved; only weak is queued for re-research
    assert state.phase == AgentPhase.RESEARCH
    assert state.retry_count == 1
    assert all(r.option_name == "Weak Option" for r in state.research_results)
    assert strong_count_before == sum(1 for o in state.scored_options if o.name == "Strong Option")
