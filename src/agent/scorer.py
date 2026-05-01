"""
scorer.py — Rubric-based scoring engine for the ADR Agent.

Owns the per-option LLM scoring call, weighted total computation,
confidence checking, and retry query suggestion.
"""

from __future__ import annotations

import json
import re

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..llm.base import LLMClient
from ..models.adr import Confidence, DimensionScore, Option
from ..models.state import IntakeResult, ResearchResult
from . import prompts

console = Console()


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score_option(
    client: LLMClient,
    intake: IntakeResult,
    result: ResearchResult,
    rubric: dict,
) -> Option:
    """
    Score a single option via one LLM call.
    Retries once with a correction prompt if the response is not valid JSON.
    """
    user_msg = prompts.SCORING_USER_TEMPLATE.format(
        intake_json=intake.model_dump_json(indent=2),
        option_json=result.model_dump_json(indent=2),
        rubric_json=json.dumps(rubric, indent=2),
    )
    messages = [{"role": "user", "content": user_msg}]

    for attempt in range(2):
        raw = client.complete(messages=messages, system=prompts.SCORING_SYSTEM, max_tokens=4096)
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        try:
            data = json.loads(clean)
            break
        except json.JSONDecodeError:
            if attempt == 0:
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "Your response was not valid JSON. Return JSON only, no markdown fences."},
                ]
            else:
                raise ValueError(
                    f"[score:{result.option_name}] LLM returned invalid JSON after retry.\nRaw:\n{raw}"
                )

    dimension_scores = [
        DimensionScore(
            dimension_id=d["dimension_id"],
            label=d["label"],
            score=d["score"],
            confidence=Confidence(d["confidence"]),
            rationale=d["rationale"],
        )
        for d in data["dimension_scores"]
    ]

    return Option(
        name=result.option_name,
        summary=result.summary,
        dimension_scores=dimension_scores,
        weighted_total=compute_weighted_total(dimension_scores, rubric),
        sources=result.sources,
    )


def score_all_options(
    client: LLMClient,
    intake: IntakeResult,
    results: list[ResearchResult],
    rubric: dict,
) -> list[Option]:
    """Score all options with a Rich spinner. Returns sorted descending by weighted total."""
    scored: list[Option] = []

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        task = progress.add_task("Scoring...", total=len(results))
        for result in results:
            progress.update(task, description=f"Scoring: {result.option_name}")
            scored.append(score_option(client, intake, result, rubric))
            progress.advance(task)

    return sorted(scored, key=lambda o: o.weighted_total, reverse=True)


# ---------------------------------------------------------------------------
# Confidence check
# ---------------------------------------------------------------------------

def check_confidence(options: list[Option], threshold: int = 2) -> list[str]:
    """Return names of options with >= threshold LOW confidence dimensions."""
    return [o.name for o in options if o.has_low_confidence(threshold)]


def suggest_retry_queries(
    client: LLMClient,
    intake: IntakeResult,
    weak_options: list[Option],
    num_queries: int = 5,
) -> list[str]:
    """
    Ask the LLM to suggest targeted web search queries for options with low-confidence
    dimensions. Returns an empty list if the LLM response cannot be parsed.
    """
    user_msg = prompts.CONFIDENCE_CHECK_USER_TEMPLATE.format(
        intake_json=intake.model_dump_json(indent=2),
        scored_options_json=json.dumps([o.model_dump() for o in weak_options], indent=2),
    )
    raw = client.complete(
        messages=[{"role": "user", "content": user_msg}],
        system=prompts.CONFIDENCE_CHECK_SYSTEM,
        max_tokens=1024,
    )
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        data = json.loads(clean)
        return data.get("suggested_queries", [])[:num_queries]
    except (json.JSONDecodeError, ValueError):
        return []


# ---------------------------------------------------------------------------
# Weighted total (also used by orchestrator)
# ---------------------------------------------------------------------------

def compute_weighted_total(dimension_scores: list[DimensionScore], rubric: dict) -> float:
    weights = {d["id"]: d["weight"] for d in rubric["dimensions"]}
    total = sum(ds.score * weights.get(ds.dimension_id, 0) for ds in dimension_scores)
    return round(total, 2)
