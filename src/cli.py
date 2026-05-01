"""
cli.py — Typer-based entry point for adr-agent.

All LLM provider wiring happens here. Orchestrator receives an LLMClient
instance — it never imports a specific provider directly.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import typer
from rich.console import Console
from rich.table import Table

from .llm import create_llm_client, MockLLMClient, DEMO_PROBLEM, DEMO_STAKEHOLDERS
from .models.adr import Domain

app = typer.Typer(
    name="adr-agent",
    help="Agentic CLI tool for generating Architecture Decision Records.",
    add_completion=False,
)
console = Console()

_DOMAIN_SLUGS: dict[str, Domain] = {
    "data-platform": Domain.DATA_PLATFORM,
    "ai-mlops": Domain.AI_MLOPS,
    "integration": Domain.INTEGRATION,
    "governance": Domain.GOVERNANCE,
    "solution-arch": Domain.SOLUTION_ARCH,
    "general": Domain.GENERAL,
}

_SEARCH_PROVIDERS = ("tavily", "firecrawl", "duckduckgo", "anthropic")

_PROJECT_ROOT = Path(__file__).parent.parent


def _resolve_domain(slug: Optional[str]) -> Optional[Domain]:
    if slug is None:
        return None
    domain = _DOMAIN_SLUGS.get(slug.lower())
    if domain is None:
        valid = ", ".join(_DOMAIN_SLUGS)
        raise typer.BadParameter(f"Unknown domain {slug!r}. Valid values: {valid}")
    return domain


def _make_search_client(provider: Optional[str]):
    """Construct a WebSearchClient from a provider name. Returns None if provider is None."""
    if provider is None:
        return None
    p = provider.lower()
    if p == "tavily":
        from .agent.researcher import TavilySearchClient
        return TavilySearchClient(api_key=os.getenv("TAVILY_API_KEY", ""))
    if p == "firecrawl":
        from .agent.researcher import FirecrawlSearchClient
        return FirecrawlSearchClient(api_key=os.getenv("FIRECRAWL_API_KEY", ""))
    if p == "duckduckgo":
        from .agent.researcher import DuckDuckGoSearchClient
        return DuckDuckGoSearchClient()
    if p == "anthropic":
        from .agent.researcher import AnthropicWebSearchClient
        return AnthropicWebSearchClient()
    valid = ", ".join(_SEARCH_PROVIDERS)
    raise typer.BadParameter(f"Unknown search provider {provider!r}. Valid: {valid}")


@app.command()
def run(
    problem_statement: str = typer.Argument(..., help="The architecture problem to solve."),
    domain: Optional[str] = typer.Option(
        None,
        "--domain", "-d",
        help=f"Domain hint. One of: {', '.join(_DOMAIN_SLUGS)}",
    ),
    stakeholders: Optional[str] = typer.Option(
        None,
        "--stakeholders", "-s",
        help='Comma-separated list of stakeholders, e.g. "Platform team, Governance".',
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Research and score only — do not write an ADR file.",
    ),
    search_provider: Optional[str] = typer.Option(
        None,
        "--search-provider",
        help=f"Web search provider: {', '.join(_SEARCH_PROVIDERS)}. Overrides env-var auto-detection.",
    ),
    no_clarify: bool = typer.Option(
        False,
        "--no-clarify",
        help="Skip contextual questions about existing systems.",
    ),
) -> None:
    """Run the full ADR agent pipeline for a given problem statement."""
    from .agent.orchestrator import run as orchestrator_run

    domain_enum = _resolve_domain(domain)
    stakeholders_list = [s.strip() for s in stakeholders.split(",")] if stakeholders else []
    search_client = _make_search_client(search_provider)

    decisions_dir = Path(os.getenv("ADR_OUTPUT_DIR", str(_PROJECT_ROOT / "decisions")))
    kb_dir = Path(__file__).parent / "kb"
    config_dir = _PROJECT_ROOT / "config"

    llm_client = create_llm_client()

    try:
        out_path = orchestrator_run(
            problem_statement=problem_statement,
            decisions_dir=decisions_dir,
            kb_dir=kb_dir,
            config_dir=config_dir,
            llm_client=llm_client,
            domain_override=domain_enum,
            stakeholders=stakeholders_list,
            dry_run=dry_run,
            search_client=search_client,
            skip_clarify=no_clarify,
        )
        if not dry_run:
            console.print(f"\n[bold green]ADR written to:[/bold green] {out_path}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command(name="list")
def list_decisions(
    last: int = typer.Option(10, "--last", "-n", help="Show the N most recent decisions."),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Decisions directory (default: ADR_OUTPUT_DIR env var or ./decisions).",
    ),
) -> None:
    """List recent ADR decisions."""
    decisions_dir = output_dir or Path(os.getenv("ADR_OUTPUT_DIR", str(_PROJECT_ROOT / "decisions")))

    if not decisions_dir.exists():
        console.print(
            f"[dim]No decisions found. Run 'adr-agent run' to create your first ADR.[/dim]"
        )
        return

    adrs = sorted(decisions_dir.glob("ADR-*.md"), reverse=True)[:last]

    if not adrs:
        console.print(f"[dim]No ADR files found in {decisions_dir}[/dim]")
        return

    table = Table(
        title=f"Architecture Decision Records  ({decisions_dir})",
        show_header=True,
        header_style="bold",
    )
    table.add_column("ADR", style="cyan", width=10)
    table.add_column("Title")
    table.add_column("Status", justify="center", width=12)
    table.add_column("Date", justify="center", width=12)

    _STATUS_COLOUR = {
        "Proposed": "yellow",
        "Accepted": "green",
        "Deprecated": "red",
        "Superseded": "dim",
    }

    for adr_file in adrs:
        content = adr_file.read_text(encoding="utf-8")

        title_m = re.search(r"^# ADR-\d+: (.+)$", content, re.MULTILINE)
        status_m = re.search(r"\*\*Status:\*\*\s*(.+)", content)
        date_m = re.search(r"\*\*Date:\*\*\s*(.+)", content)
        seq_m = re.match(r"ADR-(\d+)-", adr_file.name)

        title = title_m.group(1).strip() if title_m else "(unknown)"
        status = status_m.group(1).strip() if status_m else "—"
        date = date_m.group(1).strip() if date_m else "—"
        seq = seq_m.group(1) if seq_m else "?"

        colour = _STATUS_COLOUR.get(status, "white")
        table.add_row(
            f"ADR-{seq}",
            title,
            f"[{colour}]{status}[/{colour}]",
            date,
        )

    console.print(table)


@app.command()
def revise(
    adr_path: Path = typer.Argument(..., help="Path to the ADR file to revise."),
) -> None:
    """Open an existing ADR for agent-assisted revision."""
    from .agent.orchestrator import run_revise

    if not adr_path.exists():
        console.print(f"[red]Error:[/red] File not found: {adr_path}")
        raise typer.Exit(code=1)

    console.print(f"[dim]ADR:[/dim] {adr_path.resolve()}")
    console.print()

    revision_request = typer.prompt("What would you like to revise?", default="")
    if not revision_request.strip():
        console.print("[yellow]No revision request entered — nothing changed.[/yellow]")
        return

    llm_client = create_llm_client()

    try:
        run_revise(adr_path, revision_request.strip(), llm_client)
        console.print(f"\n[bold green]ADR revised:[/bold green] {adr_path}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command()
def demo() -> None:
    """Run the full pipeline with a mock problem statement — no API key required."""
    from .agent.orchestrator import run as orchestrator_run

    console.print("[dim]Running in demo mode — no API key required.[/dim]")

    kb_dir = Path(__file__).parent / "kb"
    config_dir = _PROJECT_ROOT / "config"

    try:
        orchestrator_run(
            problem_statement=DEMO_PROBLEM,
            decisions_dir=_PROJECT_ROOT / "decisions",
            kb_dir=kb_dir,
            config_dir=config_dir,
            llm_client=MockLLMClient(),
            stakeholders=DEMO_STAKEHOLDERS,
            dry_run=True,
            skip_clarify=True,
        )
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
