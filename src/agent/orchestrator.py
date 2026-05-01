"""
orchestrator.py — Main agentic loop for the ADR Agent.

Coordinates the pipeline:
  INTAKE → RESEARCH → SCORE → CONFIDENCE CHECK → WRITE

All phase logic is delegated to specialised modules.
All prompts live in prompts.py — never inline here.
All inter-phase objects are Pydantic-validated.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from ..kb.loader import KBLoader
from ..llm.base import LLMClient
from ..models.adr import ADR, Domain, Option
from ..models.state import AgentPhase, AgentState, IntakeResult, ResearchResult
from . import prompts
from .writer import (
    next_sequence as _next_sequence_locked,
    write_adr as _write_adr_atomic,
    append_revision,
)
from .scorer import (
    check_confidence,
    compute_weighted_total as _compute_weighted_total,
    score_all_options,
    suggest_retry_queries,
)
from .researcher import (
    WebSearchClient,
    AnthropicWebSearchClient,
    DuckDuckGoSearchClient,
    FirecrawlSearchClient,
    TavilySearchClient,
    build_search_queries,
    run_web_search,
)

console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _llm(client: LLMClient, system: str, user: str, label: str) -> str:
    """Single LLM call. Returns raw text content."""
    return client.complete(
        messages=[{"role": "user", "content": user}],
        system=system,
        max_tokens=4096,
    )


def _parse_json(raw: str, label: str) -> dict | list:
    """Strip any accidental markdown fences and parse JSON."""
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        raise ValueError(f"[{label}] Failed to parse JSON: {e}\nRaw:\n{raw}") from e


def _load_rubric(config_path: Path) -> dict:
    """Load and validate rubric weights from config/rubric.yaml."""
    import yaml
    with open(config_path) as f:
        rubric = yaml.safe_load(f)
    total = sum(d["weight"] for d in rubric["dimensions"])
    if abs(total - 1.0) > 0.001:
        raise ValueError(
            f"config/rubric.yaml: dimension weights sum to {total:.4f}, must equal 1.0"
        )
    return rubric


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:60].strip("-")


def _resolve_search_client(explicit: Optional[WebSearchClient]) -> Optional[WebSearchClient]:
    """
    Return an explicit client if provided, otherwise auto-detect from env vars.

    Priority:
      1. Caller-supplied client (explicit parameter)
      2. TAVILY_API_KEY          → TavilySearchClient
      3. FIRECRAWL_API_KEY       → FirecrawlSearchClient
      4. WEB_SEARCH_PROVIDER=duckduckgo  → DuckDuckGoSearchClient (no key needed)
      5. WEB_SEARCH_PROVIDER=anthropic   → AnthropicWebSearchClient
      6. None                    → KB-only mode (logged as a warning)
    """
    if explicit is not None:
        return explicit

    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        return TavilySearchClient(api_key=tavily_key)

    firecrawl_key = os.getenv("FIRECRAWL_API_KEY")
    if firecrawl_key:
        return FirecrawlSearchClient(api_key=firecrawl_key)

    provider = os.getenv("WEB_SEARCH_PROVIDER", "").lower()
    if provider == "duckduckgo":
        return DuckDuckGoSearchClient()
    if provider == "anthropic":
        return AnthropicWebSearchClient()

    return None


# ---------------------------------------------------------------------------
# Phase 1: INTAKE
# ---------------------------------------------------------------------------

def run_intake(state: AgentState, client: LLMClient) -> AgentState:
    console.print("[bold]Phase 1:[/bold] Parsing problem statement...", style="dim")

    user_msg = prompts.INTAKE_USER_TEMPLATE.format(
        problem_statement=state.raw_input,
        domain_override=state.domain_override.value if state.domain_override else "auto-detect",
        stakeholders=", ".join(state.stakeholders_override) if state.stakeholders_override else "not specified",
    )

    raw = _llm(client, prompts.INTAKE_SYSTEM, user_msg, "intake")
    data = _parse_json(raw, "intake")

    if state.domain_override:
        data["domain"] = state.domain_override.value
    if state.stakeholders_override:
        data["stakeholders"] = state.stakeholders_override

    state.intake = IntakeResult(
        problem_statement=data["problem_statement"],
        domain=Domain(data["domain"]),
        constraints=data.get("constraints", []),
        stakeholders=data.get("stakeholders", []),
        keywords=data.get("keywords", []),
        decision_drivers=data.get("decision_drivers", []),
    )
    state.advance(AgentPhase.CLARIFY)
    console.print(f"  Domain: [cyan]{state.intake.domain.value}[/cyan]")
    console.print(f"  Drivers: {len(state.intake.decision_drivers)} extracted")
    return state


# ---------------------------------------------------------------------------
# Phase 1b: CLARIFY
# ---------------------------------------------------------------------------

def run_clarify(state: AgentState, client: LLMClient) -> AgentState:
    """Ask the user targeted questions about their existing environment.

    Skipped automatically when: skip_clarify is set, or stdin/stdout are not a tty.
    """
    if state.skip_clarify or not _is_interactive():
        state.advance(AgentPhase.RESEARCH)
        return state

    console.print("[bold]Phase 1b:[/bold] Clarifying existing context...", style="dim")

    raw = _llm(
        client,
        prompts.CLARIFICATION_SYSTEM,
        prompts.CLARIFICATION_USER_TEMPLATE.format(
            intake_json=state.intake.model_dump_json(indent=2)
        ),
        "clarify",
    )
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        questions: list[str] = json.loads(clean)
    except json.JSONDecodeError:
        console.print("  [dim]Skipping clarification — could not parse questions.[/dim]")
        state.advance(AgentPhase.RESEARCH)
        return state

    if not questions:
        state.advance(AgentPhase.RESEARCH)
        return state

    console.print("\n[bold]A few questions about your existing environment[/bold] (Enter to skip):")
    answers: list[str] = []
    for i, q in enumerate(questions, 1):
        console.print(f"\n[cyan]{i}. {q}[/cyan]")
        try:
            answer = console.input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if answer:
            answers.append(f"Q: {q}\nA: {answer}")

    if answers:
        state.intake = state.intake.model_copy(
            update={"existing_context": "\n\n".join(answers)}
        )

    state.advance(AgentPhase.RESEARCH)
    return state


# ---------------------------------------------------------------------------
# Phase 2: RESEARCH
# ---------------------------------------------------------------------------

def run_research(
    state: AgentState,
    client: LLMClient,
    kb_dir: Path,
    search_client: Optional[WebSearchClient] = None,
) -> AgentState:
    console.print("[bold]Phase 2:[/bold] Researching options (web + KB)...", style="dim")

    # --- Web search ---
    if search_client is not None:
        # On a retry pass, use LLM-suggested queries; otherwise generate fresh ones.
        if state.suggested_queries:
            queries = state.suggested_queries
            state.suggested_queries = []
        else:
            queries = build_search_queries(client, state.intake)
        console.print(f"  Queries: [cyan]{len(queries)}[/cyan]")
        web_results = run_web_search(queries, search_client)
        total_hits = sum(len(r["results"]) for r in web_results)
        console.print(f"  Web results: [cyan]{total_hits}[/cyan]")
    else:
        console.print("  [dim]Web search: no provider configured — set TAVILY_API_KEY, FIRECRAWL_API_KEY, or WEB_SEARCH_PROVIDER[/dim]")
        web_results = []

    # --- KB lookup ---
    kb_loader = KBLoader(kb_dir)
    kb_options = kb_loader.load_patterns(state.intake.domain)
    kb_history = kb_loader.load_adr_history()
    kb_matched = kb_loader.keyword_match(kb_options + kb_history, state.intake.keywords)
    console.print(f"  KB matches: [cyan]{len(kb_matched)}[/cyan]")

    # --- Synthesis ---
    user_msg = prompts.RESEARCH_SYNTHESIS_USER_TEMPLATE.format(
        intake_json=state.intake.model_dump_json(indent=2),
        web_results=json.dumps(web_results, indent=2),
        kb_results=json.dumps(kb_matched, indent=2),
    )

    raw = _llm(client, prompts.RESEARCH_SYNTHESIS_SYSTEM, user_msg, "research")
    options_raw = _parse_json(raw, "research")

    state.research_results = [
        ResearchResult(
            option_name=o["option_name"],
            summary=o["summary"],
            evidence=o.get("evidence", []),
            sources=o.get("sources", []),
            from_kb=o.get("from_kb", False),
        )
        for o in options_raw
    ]

    console.print(f"  Options found: [cyan]{len(state.research_results)}[/cyan]")
    state.advance(AgentPhase.SCORE)
    return state


# ---------------------------------------------------------------------------
# Phase 3: SCORE
# ---------------------------------------------------------------------------

def run_scoring(
    state: AgentState,
    client: LLMClient,
    rubric: dict,
) -> AgentState:
    console.print("[bold]Phase 3:[/bold] Scoring options...", style="dim")

    # On a retry pass, merge fresh scores with previously kept strong options.
    fresh = score_all_options(client, state.intake, state.research_results, rubric)
    state.scored_options = sorted(
        list(state.scored_options) + fresh,
        key=lambda o: o.weighted_total,
        reverse=True,
    )

    _print_score_table(state.scored_options)
    state.advance(AgentPhase.CONFIDENCE_CHECK)
    return state


def _print_score_table(options: list[Option]) -> None:
    table = Table(title="Trade-off scores", show_header=True, header_style="bold")
    table.add_column("Option", style="cyan")
    table.add_column("Fit", justify="center")
    table.add_column("Maturity", justify="center")
    table.add_column("Cost", justify="center")
    table.add_column("Ops", justify="center")
    table.add_column("Risk", justify="center")
    table.add_column("Skills", justify="center")
    table.add_column("Total", justify="right", style="bold")

    for opt in options:
        scores_by_id = {d.dimension_id: d.score for d in opt.dimension_scores}
        table.add_row(
            opt.name,
            str(scores_by_id.get("fit", "-")),
            str(scores_by_id.get("maturity", "-")),
            str(scores_by_id.get("cost", "-")),
            str(scores_by_id.get("ops", "-")),
            str(scores_by_id.get("risk", "-")),
            str(scores_by_id.get("skill_match", "-")),
            f"{opt.weighted_total:.1f}",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Phase 4: CONFIDENCE CHECK
# ---------------------------------------------------------------------------

def run_confidence_check(
    state: AgentState,
    client: LLMClient,
    kb_dir: Path,
    rubric: dict,
) -> AgentState:
    console.print("[bold]Phase 4:[/bold] Confidence check...", style="dim")

    threshold = rubric.get("confidence", {}).get("low_threshold", 2)
    weak_names = set(check_confidence(state.scored_options, threshold))

    if not weak_names:
        console.print("  All options have sufficient evidence. Proceeding.")
        state.advance(AgentPhase.WRITE)
        return state

    if not state.needs_retry():
        console.print(
            f"  [yellow]Warning:[/yellow] {len(weak_names)} option(s) have low-confidence dimensions. "
            "Max retries reached — proceeding anyway."
        )
        state.advance(AgentPhase.WRITE)
        return state

    console.print(
        f"  [yellow]{len(weak_names)} option(s) flagged for re-research[/yellow] "
        f"(retry {state.retry_count + 1}/{state.max_retries})"
    )

    # Ask the LLM for targeted re-search queries before clearing weak options.
    weak_options = [o for o in state.scored_options if o.name in weak_names]
    state.suggested_queries = suggest_retry_queries(client, state.intake, weak_options)

    # Keep strong scored options; re-research only weak ones.
    state.research_results = [r for r in state.research_results if r.option_name in weak_names]
    state.scored_options = [o for o in state.scored_options if o.name not in weak_names]

    state.retry_count += 1
    state.advance(AgentPhase.RESEARCH)
    return state


# ---------------------------------------------------------------------------
# Phase 5: WRITE
# ---------------------------------------------------------------------------

def run_write(
    state: AgentState,
    client: LLMClient,
    decisions_dir: Path,
    rubric: dict,
) -> tuple[AgentState, Path]:
    console.print("[bold]Phase 5:[/bold] Generating ADR...", style="dim")

    user_msg = prompts.DECISION_USER_TEMPLATE.format(
        intake_json=state.intake.model_dump_json(indent=2),
        scored_options_json=json.dumps(
            [o.model_dump() for o in state.scored_options], indent=2
        ),
    )
    raw = _llm(client, prompts.DECISION_SYSTEM, user_msg, "decision")
    decision_data = _parse_json(raw, "decision")

    sequence = _next_sequence_locked(decisions_dir)
    slug = _slugify(state.intake.problem_statement[:60])

    adr = ADR(
        sequence=sequence,
        slug=slug,
        title=f"Decision on: {state.intake.problem_statement[:80]}",
        domain=state.intake.domain,
        problem_statement=state.intake.problem_statement,
        decision_drivers=state.intake.decision_drivers,
        options=state.scored_options,
        chosen_option=decision_data["chosen_option"],
        decision_rationale=decision_data["decision_rationale"],
        consequences_positive=decision_data.get("consequences_positive", []),
        consequences_negative=decision_data.get("consequences_negative", []),
        consequences_neutral=decision_data.get("consequences_neutral", []),
        open_questions=decision_data.get("open_questions", []),
        deciders=state.intake.stakeholders,
    )

    writer_msg = prompts.WRITER_USER_TEMPLATE.format(
        adr_json=adr.model_dump_json(indent=2)
    )
    markdown = _llm(client, prompts.WRITER_SYSTEM, writer_msg, "writer")

    out_path = decisions_dir / adr.filename
    if not state.dry_run:
        _write_adr_atomic(markdown, out_path)
        console.print(f"\n  [green]Written:[/green] {out_path}")
    else:
        console.print(f"\n  [yellow]Dry run:[/yellow] would write {out_path}")
        console.print("\n" + markdown)

    state.advance(AgentPhase.DONE)
    return state, out_path


# ---------------------------------------------------------------------------
# Standalone: revise an existing ADR
# ---------------------------------------------------------------------------

def run_revise(
    adr_path: Path,
    revision_request: str,
    client: LLMClient,
) -> None:
    """Apply LLM-assisted revision to an existing ADR and append a revision history entry."""
    import datetime
    console.print("[bold]Revising ADR…[/bold]", style="dim")

    current_content = adr_path.read_text(encoding="utf-8")
    raw = _llm(
        client,
        prompts.REVISE_SYSTEM,
        prompts.REVISE_USER_TEMPLATE.format(
            current_adr=current_content,
            revision_request=revision_request,
        ),
        "revise",
    )

    _write_adr_atomic(raw, adr_path)
    append_revision(adr_path, revision_request)
    console.print(f"  [green]Revised:[/green] {adr_path}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    problem_statement: str,
    decisions_dir: Path,
    kb_dir: Path,
    config_dir: Path,
    llm_client: LLMClient,
    domain_override: Optional[Domain] = None,
    stakeholders: Optional[list[str]] = None,
    dry_run: bool = False,
    max_retries: int = 2,
    search_client: Optional[WebSearchClient] = None,
    skip_clarify: bool = False,
) -> Path:
    """
    Run the full ADR agent pipeline.
    Returns the path to the written (or would-be-written) ADR file.

    search_client: explicit WebSearchClient instance, or None to auto-detect
    from environment variables (TAVILY_API_KEY, FIRECRAWL_API_KEY, WEB_SEARCH_PROVIDER).
    """
    rubric = _load_rubric(config_dir / "rubric.yaml")
    max_retries = rubric.get("retry", {}).get("max_retries", max_retries)
    resolved_search_client = _resolve_search_client(search_client)

    state = AgentState(
        raw_input=problem_statement,
        domain_override=domain_override,
        stakeholders_override=stakeholders or [],
        dry_run=dry_run,
        max_retries=max_retries,
        skip_clarify=skip_clarify,
    )

    console.rule("[bold]ADR Agent[/bold]")

    while state.phase not in (AgentPhase.DONE, AgentPhase.FAILED):
        if state.phase == AgentPhase.INTAKE:
            state = run_intake(state, llm_client)

        elif state.phase == AgentPhase.CLARIFY:
            state = run_clarify(state, llm_client)

        elif state.phase == AgentPhase.RESEARCH:
            state = run_research(state, llm_client, kb_dir, resolved_search_client)

        elif state.phase == AgentPhase.SCORE:
            state = run_scoring(state, llm_client, rubric)

        elif state.phase == AgentPhase.CONFIDENCE_CHECK:
            state = run_confidence_check(state, llm_client, kb_dir, rubric)

        elif state.phase == AgentPhase.WRITE:
            state, out_path = run_write(state, llm_client, decisions_dir, rubric)

    if state.phase == AgentPhase.FAILED:
        for err in state.errors:
            console.print(f"[red]Error:[/red] {err}")
        raise RuntimeError("ADR Agent pipeline failed. See errors above.")

    console.rule("[bold green]Done[/bold green]")
    return out_path
