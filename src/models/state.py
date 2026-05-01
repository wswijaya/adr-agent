from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .adr import Domain


class AgentPhase(str, Enum):
    INTAKE = "intake"
    CLARIFY = "clarify"
    RESEARCH = "research"
    SCORE = "score"
    CONFIDENCE_CHECK = "confidence_check"
    WRITE = "write"
    DONE = "done"
    FAILED = "failed"


class ResearchResult(BaseModel):
    option_name: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    from_kb: bool = False


class IntakeResult(BaseModel):
    problem_statement: str
    domain: Domain
    constraints: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    decision_drivers: list[str] = Field(default_factory=list)
    existing_context: str = ""


class AgentState(BaseModel):
    # Input
    raw_input: str
    domain_override: Optional[Domain] = None
    stakeholders_override: list[str] = Field(default_factory=list)
    dry_run: bool = False
    skip_clarify: bool = False

    # Phase tracking
    phase: AgentPhase = AgentPhase.INTAKE
    retry_count: int = 0
    max_retries: int = 2

    # Accumulated results
    intake: Optional[IntakeResult] = None
    research_results: list[ResearchResult] = Field(default_factory=list)
    scored_options: list[Any] = Field(default_factory=list)  # list[Option] — avoids circular
    suggested_queries: list[str] = Field(default_factory=list)  # targeted queries for retry pass
    errors: list[str] = Field(default_factory=list)

    def advance(self, phase: AgentPhase) -> None:
        self.phase = phase

    def record_error(self, msg: str) -> None:
        self.errors.append(msg)

    def needs_retry(self) -> bool:
        return self.retry_count < self.max_retries
