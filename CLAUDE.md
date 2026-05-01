# ADR Agent — Claude Code Project Context

## What this project does

This is an agentic CLI tool that accepts an IT and Software architecture problem statement and autonomously:

1. Researches solution options via web search and an internal knowledge base
2. Scores each option against a configurable trade-off rubric
3. Writes a structured Architecture Decision Record (ADR) markdown file to `/decisions/`

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
INTAKE → CLARIFY → RESEARCH → SCORE → CONFIDENCE CHECK → WRITE
                               ↑________________↓ (retry if confidence low, max 2x)
```

### Phase details

**INTAKE** — Parse problem statement. Extract: domain, constraints, stakeholders, keywords.

**CLARIFY** — Ask 2–4 targeted questions about existing systems and constraints. Skipped when `--no-clarify` is passed or stdin is not a tty. Answers are stored in `IntakeResult.existing_context` and flow into all downstream prompts automatically.

**RESEARCH** — Web search + KB lookup → synthesise 3–5 candidate options. On a retry pass, uses LLM-suggested queries from `state.suggested_queries` instead of generating fresh ones.

**SCORE** — For each option, score all 6 rubric dimensions → one-sentence rationale → compute weighted total. Retries once with a correction prompt on JSON parse failure.

**CONFIDENCE CHECK** — If any option has ≥2 dimensions flagged "low confidence", trigger re-research. Strong options are preserved; only weak ones re-enter RESEARCH. Max 2 retries (configurable in `config/rubric.yaml`).

**WRITE** — Render ADR via LLM → atomically write to `/decisions/ADR-NNNN-{slug}.md` (`.tmp` + rename) with file-locked sequence allocation.

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

