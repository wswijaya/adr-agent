# adr-agent

An agentic CLI tool that accepts an IT or software architecture problem statement and autonomously:

1. Parses the problem and asks targeted clarifying questions about your existing environment
2. Researches solution options via web search and an internal knowledge base
3. Scores each option against a configurable trade-off rubric
4. Writes a structured **Architecture Decision Record** (ADR) to `/decisions/`

---

## Quick start

```bash
# Install
pip install -e .

# Run in demo mode — no API key needed
adr-agent demo

# Run the full pipeline
export ANTHROPIC_API_KEY=sk-ant-...
adr-agent run "We need to choose a streaming platform for 10M IoT events/day with schema evolution support and a $5k/month budget"
```

---

## Installation

Python 3.11+ required.

```bash
pip install -e .
```

### Optional: web search providers

Without a search provider the agent uses only the built-in knowledge base.

| Provider | Setup |
|---|---|
| **Tavily** (recommended) | `pip install tavily-python` → `export TAVILY_API_KEY=...` |
| **Firecrawl** | `pip install firecrawl-py` → `export FIRECRAWL_API_KEY=...` |
| **DuckDuckGo** | `pip install duckduckgo-search` → `--search-provider duckduckgo` |
| **Anthropic web search** | uses your `ANTHROPIC_API_KEY` → `--search-provider anthropic` |

---

## LLM providers

Set `LLM_PROVIDER` to switch backends. Default is `anthropic`.

| Provider | Env var | Default model |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-4-7` |
| `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| `ollama` | — | `llama3.2` |
| `azure` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` | `gpt-4o` |

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
adr-agent run "..."

# Local Ollama
export LLM_PROVIDER=ollama
adr-agent run "..."
```

---

## CLI commands

### `run` — generate an ADR

```bash
adr-agent run "<problem statement>" [OPTIONS]

Options:
  -d, --domain          Domain hint: data-platform, ai-mlops, integration,
                        governance, solution-arch, general
  -s, --stakeholders    Comma-separated list, e.g. "Platform team, Data Eng"
  --dry-run             Research and score only — do not write a file
  --search-provider     Override web search: tavily, firecrawl, duckduckgo, anthropic
  --no-clarify          Skip the contextual questions about existing systems
```

### `list` — view recent decisions

```bash
adr-agent list [--last 10] [--dir ./decisions]
```

### `revise` — agent-assisted ADR revision

```bash
adr-agent revise decisions/ADR-0003-stream-ingest.md
# Prompts: "What would you like to revise?"
# Applies the change, appends a dated revision history entry
```

### `demo` — no API key required

```bash
adr-agent demo
```

Runs the full pipeline on a canonical streaming platform decision using a mock LLM client. No API key or network access needed.

---

## Agent pipeline

```
INTAKE → CLARIFY → RESEARCH → SCORE → CONFIDENCE CHECK → WRITE
                               ↑__________________↓  (retry if confidence low, max 2×)
```

| Phase | What happens |
|---|---|
| **INTAKE** | Parse problem statement; extract domain, constraints, stakeholders, keywords |
| **CLARIFY** | Ask 2–4 targeted questions about your existing environment (skipped with `--no-clarify`) |
| **RESEARCH** | Web search + KB lookup → synthesise 3–5 candidate options |
| **SCORE** | Score each option across 6 rubric dimensions; compute weighted total |
| **CONFIDENCE CHECK** | Flag options with ≥2 low-confidence dimensions; re-research if retries remain |
| **WRITE** | Render ADR markdown → write atomically to `/decisions/ADR-NNNN-{slug}.md` |

---

## Scoring rubric

Six dimensions, each scored 1–5. Weights are in `config/rubric.yaml` — edit there, not in code.

| Dimension | Weight | Measures |
|---|---|---|
| `fit` | 0.25 | How directly the option addresses the problem |
| `maturity` | 0.20 | Ecosystem stability, community, vendor support |
| `cost` | 0.15 | Total cost of ownership |
| `ops` | 0.15 | Ongoing operational burden |
| `risk` | 0.15 | Vendor lock-in, compliance exposure |
| `skill_match` | 0.10 | Proximity to existing team skills |

Weighted total = Σ(score × weight). Range: 1.0–5.0.

To tune weights: edit `config/rubric.yaml`. The agent validates that weights sum to 1.0 on startup.

---

## Output format

Every generated file follows this structure:

```
decisions/ADR-NNNN-{kebab-slug}.md
```

```markdown
# ADR-NNNN: {Title}

**Status:** Proposed
**Date:** YYYY-MM-DD
**Deciders:** ...
**Domain:** ...

## Context and problem statement
## Decision drivers
## Options considered       ← score table per option
## Decision                 ← chosen option + rationale
## Consequences             ← positive / negative / neutral
## Open questions
## References
## Revision history         ← appended by `adr-agent revise`
```

Files are append-only. The `revise` command appends a `## Revision history` entry; it never silently overwrites content.

---

## Knowledge base

The built-in KB covers four domains (`src/kb/patterns/`):

| Domain | File | Typical decisions |
|---|---|---|
| Data Platform | `data_platform.yaml` | Warehouse, lakehouse, streaming |
| AI/ML & MLOps | `ai_mlops.yaml` | Model registry, feature store, serving |
| Integration & API | `integration.yaml` | API styles, messaging, eventing |
| Governance & Security | `governance.yaml` | Catalog, lineage, access control |

Drop past ADR `.md` files into `src/kb/adr_history/` to give the agent context from previous decisions.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for Anthropic provider |
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, `ollama`, `azure` |
| `TAVILY_API_KEY` | — | Enables Tavily web search |
| `FIRECRAWL_API_KEY` | — | Enables Firecrawl web search |
| `WEB_SEARCH_PROVIDER` | — | `duckduckgo` or `anthropic` (no-key variants) |
| `ADR_OUTPUT_DIR` | `./decisions` | Output directory for generated ADRs |
| `ADR_MAX_RETRIES` | `2` | Max confidence-check retry passes |

---

## Development

```bash
# Install with dev dependencies
pip install -e .
pip install pytest

# Run tests (no API key needed — all tests use MockLLMClient)
python3 -m pytest tests/ -q

# Run a specific test file
python3 -m pytest tests/test_scorer.py -v
```

### Project structure

```
src/
├── agent/
│   ├── orchestrator.py   # Main agentic loop & phase state machine
│   ├── researcher.py     # Web search + KB retrieval
│   ├── scorer.py         # Rubric-based scoring engine
│   ├── writer.py         # Atomic file writes & revision history
│   └── prompts.py        # All system prompts (primary tuning surface)
├── kb/
│   ├── loader.py         # KB ingestion & keyword matching
│   ├── patterns/         # Pre-seeded architecture pattern YAML files
│   └── adr_history/      # Drop past ADRs here for context
├── llm/
│   ├── base.py           # LLMClient ABC
│   ├── factory.py        # Provider selection
│   ├── anthropic_client.py
│   ├── openai_compatible_client.py
│   └── mock_client.py    # Deterministic responses for demo & tests
├── models/
│   ├── adr.py            # Pydantic: ADR, Option, DimensionScore
│   └── state.py          # Pydantic: AgentState, IntakeResult
└── cli.py                # Typer CLI entry point
config/
└── rubric.yaml           # Scoring weights & retry config
decisions/                # Generated ADRs (git-tracked)
tests/
├── fixtures/             # Canned research & scoring data
├── test_smoke.py
├── test_researcher.py
├── test_scorer.py
├── test_writer.py
└── test_cli.py
```

### Prompt engineering

Output quality is almost entirely determined by `src/agent/prompts.py`. The scoring prompt is the highest-leverage surface — it controls chain-of-thought ordering (reasoning → score → confidence). When tuning, use the canonical streaming platform test case in `tests/fixtures/` as ground truth.

---

## License

MIT
