from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Domain(str, Enum):
    DATA_PLATFORM = "Data Platform"
    AI_MLOPS = "AI/ML & MLOps"
    INTEGRATION = "Integration & API"
    GOVERNANCE = "Governance & Security"
    SOLUTION_ARCH = "Solution Architecture"
    GENERAL = "General IT"


class ADRStatus(str, Enum):
    PROPOSED = "Proposed"
    ACCEPTED = "Accepted"
    DEPRECATED = "Deprecated"
    SUPERSEDED = "Superseded"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DimensionScore(BaseModel):
    dimension_id: str
    label: str
    score: int = Field(ge=1, le=5)
    confidence: Confidence
    rationale: str


class Option(BaseModel):
    name: str
    summary: str
    dimension_scores: list[DimensionScore]
    weighted_total: float = Field(ge=1.0, le=5.0)
    sources: list[str] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)

    def has_low_confidence(self, threshold: int = 2) -> bool:
        low = [d for d in self.dimension_scores if d.confidence == Confidence.LOW]
        return len(low) >= threshold


class ADR(BaseModel):
    sequence: int
    slug: str
    title: str
    status: ADRStatus = ADRStatus.PROPOSED
    date: datetime.date = Field(default_factory=datetime.date.today)
    deciders: list[str] = Field(default_factory=list)
    domain: Domain = Domain.GENERAL
    problem_statement: str
    decision_drivers: list[str] = Field(default_factory=list)
    options: list[Option] = Field(default_factory=list)
    chosen_option: Optional[str] = None
    decision_rationale: str = ""
    consequences_positive: list[str] = Field(default_factory=list)
    consequences_negative: list[str] = Field(default_factory=list)
    consequences_neutral: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"ADR-{self.sequence:04d}-{self.slug}.md"
