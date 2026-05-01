# ADR Agent — Claude Code Project Context

## What this project does

This is an agentic CLI tool that accepts an IT and Software architecture problem statement and autonomously:

1. Researches solution options via web search and an internal knowledge base
2. Scores each option against a configurable trade-off rubric
3. Writes a structured Architecture Decision Record (ADR) markdown file to `/decisions/`

---

## Project structure

```
adr-agent/
├── CLAUDE.md                        ← you are here
├── src/
│   ├── agent/
│   │   ├── orchestrator.py          # Main agentic loop & state machine
│   │   ├── researcher.py            # Web search + KB retrieval
│   │   ├── scorer.py                # Rubric-based scoring engine
│   │   ├── writer.py                # ADR template renderer & file writer
│   │   └── prompts.py               # All system prompts (primary tuning surface)
│   ├── kb/
│   │   ├── loader.py                # KB ingestion & indexing
│   │   ├── patterns/                # Pre-seeded architecture pattern files (YAML)
│   │   │   ├── data_platform.yaml
│   │   │   ├── ai_mlops.yaml
│   │   │   ├── integration.yaml
│   │   │   └── governance.yaml
│   │   └── adr_history/             # Past ADRs for context (drop .md files here)
│   ├── models/
│   │   ├── adr.py                   # Pydantic: ADR, Option, Score
│   │   └── state.py                 # Pydantic: AgentState, ResearchResult
│   └── cli.py                       # Typer-based CLI entry point
├── decisions/                       # Generated ADRs land here (git-tracked)
├── config/
│   └── rubric.yaml                  # Scoring weights — edit here, not in code
├── tests/
│   ├── test_scorer.py
│   └── fixtures/
└── requirements.txt
```

---

## Tech stack

| Layer           | Library / Tool                     | Notes                                             |
| --------------- | ---------------------------------- | ------------------------------------------------- |
| Language        | Python 3.11+                       |                                                   |
| CLI framework   | Typer                              | Built on Click; typed commands, `--help` auto-gen |
| Terminal output | Rich                               | Tables, spinners, markdown preview, colour        |
| LLM client      | `anthropic` SDK                    | Tool use, structured output                       |
| Web search      | Tavily API or Anthropic web search | Tavily preferred for structured technical results |
| Data validation | Pydantic v2                        | Every state transition is validated               |
| KB format       | YAML + JSON                        | Human-editable, version-controllable              |
| Output format   | Markdown                           | Written to `/decisions/`, git-diffable            |

---

## Agent loop (how the pipeline works)

```
INTAKE → RESEARCH → SCORE → CONFIDENCE CHECK → WRITE
                    ↑________________↓ (retry if confidence low, max 2x)
```

### Phase details

**INTAKE** — Parse problem statement. Extract: domain, constraints, stakeholders, keywords.

**RESEARCH** — Run parallel sub-tasks:

- Web search: 3–5 targeted queries per option candidate (current vendor docs, RFCs, benchmarks)
- KB lookup: semantic match against `kb/patterns/` and `kb/adr_history/`
- Synthesise: deduplicate, rank by relevance, generate 3–5 option candidates

**SCORE** — For each option, score all 6 rubric dimensions → generate one-sentence rationale per dimension → compute weighted total.

**CONFIDENCE CHECK** — If any option has >2 dimensions flagged "low confidence", trigger re-research. Max 2 retries (configurable in `config/rubric.yaml`).

**WRITE** — Render ADR template → write to `/decisions/ADR-NNNN-{slug}.md` → print summary table to terminal via Rich.

---

## Scoring rubric (config/rubric.yaml)

Six dimensions, each scored 1–5 by the agent. Weights are externalised — **tune in the YAML, not in code**.

| Dimension     | Default weight | What it measures                                       |
| ------------- | -------------- | ------------------------------------------------------ |
| `fit`         | 0.25           | How directly does the option address the problem?      |
| `maturity`    | 0.20           | Ecosystem stability, community, vendor support         |
| `cost`        | 0.15           | TCO, licensing model, infra overhead                   |
| `ops`         | 0.15           | Ongoing maintenance, observability, runbook complexity |
| `risk`        | 0.15           | Vendor lock-in, data sovereignty, compliance exposure  |
| `skill_match` | 0.10           | Proximity to existing team competencies                |

Weighted total = sum(score × weight) across all dimensions. Range: 1.0–5.0.

---

## ADR domain taxonomy

The KB covers these domain-to-file mappings:

| Domain                | Pattern file       | Typical decision types                     |
| --------------------- | ------------------ | ------------------------------------------ |
| Data Platform         | data_platform.yaml | Storage formats, warehouse, lakehouse      |
| AI/ML & MLOps         | ai_mlops.yaml      | Model registry, feature store, serving     |
| Integration & API     | integration.yaml   | Protocols, API styles, messaging, eventing |
| Governance & Security | governance.yaml    | Catalog, lineage, access control, policy   |

---

## ADR output format

Every generated file follows this structure:

```markdown
# ADR-NNNN: {Title}

**Status:** Proposed
**Date:** YYYY-MM-DD
**Deciders:** {from input context}
**Domain:** {Data Platform | AI/ML | Integration | Governance | Solution Arch}

## Context & Problem Statement

## Decision Drivers

## Options Considered

### Option N: {Name}

Scores per dimension + weighted total + rationale + sources

## Decision

## Consequences

## Open Questions

## References
```

Files are named `ADR-NNNN-{kebab-slug}.md` with auto-incremented sequence numbers.

---

## CLI commands

```bash
# Primary command — run the full agent pipeline
adr-agent run "<problem statement>"

# With optional context flags
adr-agent run "<problem statement>" --domain data-platform --stakeholders "Platform team, Governance"

# Dry run — research + score only, no file written
adr-agent run "<problem statement>" --dry-run

# List recent decisions
adr-agent list --last 5

# Open an existing ADR for agent-assisted revision
adr-agent revise decisions/ADR-0003-stream-ingest.md
```

---

## Key files to understand first

When picking up a task in this project, read these in order:

1. `config/rubric.yaml` — scoring weights and retry config
2. `src/agent/prompts.py` — all system prompts; this is the primary quality tuning surface
3. `src/models/adr.py` and `src/models/state.py` — data shapes passed between pipeline phases
4. `src/agent/orchestrator.py` — the main loop

---

## Conventions

- **Pydantic everywhere.** Every object crossing a phase boundary (intake → research → score → write) must be a validated Pydantic model. No raw dicts passed between agent phases.
- **Prompts are not inline.** All system prompts and few-shot examples live in `src/agent/prompts.py` only. Do not embed prompt strings in orchestrator or scorer logic.
- **Rubric weights are not in code.** Scoring weights, retry limits, and confidence thresholds live in `config/rubric.yaml`. Code reads from config; config is not regenerated by code.
- **ADR files are append-only.** Never overwrite an existing ADR. Use `adr revise` which creates a new revision section rather than mutating the original.
- **One ADR per run.** The agent scopes each run to a single decision. Do not attempt to batch multiple problem statements in one invocation.
- **Rich for all terminal output.** Use Rich tables for score summaries, Rich spinners for research and scoring phases, Rich markdown for ADR preview. No bare `print()` in agent code.
- **Tests use fixtures, not live search.** `tests/fixtures/` contains canned research results and KB snapshots. Tests must not call the Tavily API or Anthropic API.

---

## Prompt engineering notes (important)

Output quality is almost entirely determined by `src/agent/prompts.py`. When iterating:

- The **scoring prompt** is the highest-leverage surface. It must instruct the model to score each dimension independently, produce a confidence flag ("high" / "medium" / "low"), and give a one-sentence rationale before the numeric score — order matters for chain-of-thought.
- The **research synthesis prompt** must explicitly instruct the model to deduplicate across web and KB results, and to discard options with insufficient evidence rather than hallucinating support.
- When tuning, use the canonical test case in `tests/fixtures/` — a real decision with a known correct answer — as your ground truth. Do not consider a prompt version stable until it consistently converges on that answer.

---

## Environment variables

```bash
ANTHROPIC_API_KEY=          # Required
TAVILY_API_KEY=             # Required if using Tavily for web search
ADR_OUTPUT_DIR=./decisions  # Optional override for output path
ADR_MAX_RETRIES=2           # Optional override for confidence retry limit
```

---

## Current build phases

| Phase              | Scope                                             | Status         |
| ------------------ | ------------------------------------------------- | -------------- |
| 1 — Foundation     | CLI wired, LLM call, raw markdown output          | 🔲 Not started |
| 2 — Research layer | Web search + KB loader + pattern files seeded     | 🔲 Not started |
| 3 — Scoring & loop | Rubric engine, confidence check, retry logic      | 🔲 Not started |
| 4 — Polish         | ADR numbering, `list`, `revise`, stakeholder flag | 🔲 Not started |
| 5 — Web UI (later) | FastAPI backend + React frontend                  | 🔲 Backlog     |
