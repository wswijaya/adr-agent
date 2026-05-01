"""
MockLLMClient — deterministic responses for demo and testing.

Returns canned JSON/markdown for each pipeline phase, detected by
keywords in the system prompt. No API key or network access required.

Demo problem: streaming platform selection for 10M IoT events/day.
"""

from __future__ import annotations

import json
import re

from .base import LLMClient

DEMO_PROBLEM = (
    "We need to choose a streaming platform for processing 10 million IoT sensor "
    "events per day in real time, with schema evolution support and a budget "
    "under $5,000/month."
)

DEMO_STAKEHOLDERS = ["Platform team", "IoT Engineering", "Data Engineering"]

# ---------------------------------------------------------------------------
# Canned phase responses
# ---------------------------------------------------------------------------

_INTAKE = {
    "problem_statement": DEMO_PROBLEM,
    "domain": "Data Platform",
    "constraints": [
        "Budget under $5,000/month at target scale",
        "Must support schema evolution",
        "Cloud-native or fully managed deployment",
    ],
    "stakeholders": DEMO_STAKEHOLDERS,
    "keywords": ["streaming", "kafka", "kinesis", "event streaming", "iot", "real-time", "schema registry"],
    "decision_drivers": [
        "Low operational overhead",
        "High throughput at 10M events/day",
        "Schema evolution support",
        "Cost efficiency",
        "Real-time processing latency < 500ms",
    ],
}

_RESEARCH = [
    {
        "option_name": "Apache Kafka on Confluent Cloud",
        "summary": (
            "Fully managed Kafka service with Schema Registry, ksqlDB, and 200+ connectors. "
            "Provides exactly-once semantics and horizontal scalability for IoT event pipelines."
        ),
        "evidence": [
            "99.99% SLA with auto-scaling clusters",
            "Schema Registry enforces Avro/Protobuf/JSON schema evolution rules",
            "Kafka Connect has 200+ source/sink connectors",
        ],
        "sources": ["https://docs.confluent.io/cloud/current/overview.html"],
        "from_kb": False,
    },
    {
        "option_name": "AWS Kinesis Data Streams",
        "summary": (
            "AWS-native serverless streaming service with on-demand capacity scaling. "
            "Deep integration with Lambda, S3, Glue Schema Registry, and Redshift for analytics pipelines."
        ),
        "evidence": [
            "On-demand mode scales automatically, no shard management required",
            "Glue Schema Registry supports Avro and JSON Schema evolution",
            "Lambda triggers enable serverless, event-driven processing",
        ],
        "sources": ["https://docs.aws.amazon.com/streams/latest/dev/introduction.html"],
        "from_kb": False,
    },
    {
        "option_name": "Azure Event Hubs",
        "summary": (
            "Fully managed event streaming platform with Kafka protocol compatibility. "
            "Integrates natively with Azure services and supports Schema Registry via Azure Schema Registry."
        ),
        "evidence": [
            "Kafka surface API allows drop-in replacement for Kafka producers/consumers",
            "Azure Schema Registry supports Avro and JSON Schema",
            "Event Capture writes to Azure Blob Storage or ADLS Gen2 automatically",
        ],
        "sources": ["https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-about"],
        "from_kb": False,
    },
]

_SCORES: dict[str, dict] = {
    "apache kafka on confluent cloud": {
        "option_name": "Apache Kafka on Confluent Cloud",
        "dimension_scores": [
            {"dimension_id": "fit",         "label": "Problem fit",             "rationale": "Kafka is purpose-built for high-throughput event streaming and handles 10M+ events/day natively with Schema Registry meeting the evolution constraint.", "score": 5, "confidence": "high"},
            {"dimension_id": "maturity",    "label": "Ecosystem maturity",      "rationale": "De-facto industry standard with 10+ years of production use, large community, and enterprise support from Confluent.", "score": 5, "confidence": "high"},
            {"dimension_id": "cost",        "label": "Total cost of ownership", "rationale": "Confluent Cloud at this scale typically runs $1,500–$3,000/month, comfortably within the $5k budget.", "score": 4, "confidence": "medium"},
            {"dimension_id": "ops",         "label": "Operational overhead",    "rationale": "Fully managed — cluster sizing, replication, and Schema Registry are hosted; consumer lag monitoring is the main operational task.", "score": 4, "confidence": "high"},
            {"dimension_id": "risk",        "label": "Risk and lock-in",        "rationale": "Confluent-specific features (ksqlDB, Tiered Storage) create moderate lock-in; the open Kafka protocol reduces migration risk somewhat.", "score": 3, "confidence": "high"},
            {"dimension_id": "skill_match", "label": "Skill match",             "rationale": "Kafka expertise is widely available; most platform engineers have prior exposure reducing ramp-up time.", "score": 4, "confidence": "medium"},
        ],
    },
    "aws kinesis data streams": {
        "option_name": "AWS Kinesis Data Streams",
        "dimension_scores": [
            {"dimension_id": "fit",         "label": "Problem fit",             "rationale": "Handles the throughput requirements well but lacks native schema evolution — Glue Schema Registry is a separate service with added integration complexity.", "score": 3, "confidence": "high"},
            {"dimension_id": "maturity",    "label": "Ecosystem maturity",      "rationale": "Mature AWS service with strong SLA and long track record, though its open-source ecosystem is narrower than Kafka's.", "score": 4, "confidence": "high"},
            {"dimension_id": "cost",        "label": "Total cost of ownership", "rationale": "On-demand mode at 10M events/day estimated at $800–$1,500/month — the most cost-effective option evaluated.", "score": 5, "confidence": "medium"},
            {"dimension_id": "ops",         "label": "Operational overhead",    "rationale": "Fully serverless with on-demand mode; no shard management; native CloudWatch metrics reduce monitoring setup.", "score": 5, "confidence": "high"},
            {"dimension_id": "risk",        "label": "Risk and lock-in",        "rationale": "Deep AWS ecosystem coupling; migrating consumers and producers to another platform requires significant rework.", "score": 2, "confidence": "high"},
            {"dimension_id": "skill_match", "label": "Skill match",             "rationale": "Strong fit for AWS-native teams; teams with Kafka backgrounds will face a learning curve around Kinesis-specific concepts.", "score": 3, "confidence": "medium"},
        ],
    },
    "azure event hubs": {
        "option_name": "Azure Event Hubs",
        "dimension_scores": [
            {"dimension_id": "fit",         "label": "Problem fit",             "rationale": "Kafka-compatible surface covers the use case, but schema evolution requires the Azure Schema Registry add-on, adding integration overhead.", "score": 3, "confidence": "medium"},
            {"dimension_id": "maturity",    "label": "Ecosystem maturity",      "rationale": "Mature Azure service with enterprise support; Kafka compatibility layer has known edge cases with certain client libraries.", "score": 4, "confidence": "medium"},
            {"dimension_id": "cost",        "label": "Total cost of ownership", "rationale": "Premium tier required for Kafka compatibility; estimated $2,000–$3,500/month at scale, within budget but more expensive than Kinesis.", "score": 3, "confidence": "medium"},
            {"dimension_id": "ops",         "label": "Operational overhead",    "rationale": "Managed service with auto-inflate scaling; Azure Schema Registry adds a separate management surface that must be monitored independently.", "score": 3, "confidence": "medium"},
            {"dimension_id": "risk",        "label": "Risk and lock-in",        "rationale": "Azure-specific lock-in; Kafka protocol compatibility reduces but does not eliminate migration complexity.", "score": 3, "confidence": "medium"},
            {"dimension_id": "skill_match", "label": "Skill match",             "rationale": "Best fit for Azure-native teams; teams with strong Kafka backgrounds will find the compatibility layer introduces friction.", "score": 2, "confidence": "medium"},
        ],
    },
}

_DECISION = {
    "chosen_option": "Apache Kafka on Confluent Cloud",
    "decision_rationale": (
        "Apache Kafka on Confluent Cloud scores highest overall (4.15/5.0) and best satisfies the primary decision drivers. "
        "Its native Schema Registry directly addresses the schema evolution hard requirement, and its maturity and ecosystem "
        "breadth reduce delivery and hiring risk.\n\n"
        "AWS Kinesis offers lower cost and zero operational overhead, but schema evolution requires Glue Schema Registry as a "
        "separate service — introducing integration complexity that conflicts with the low-overhead driver. It is the right "
        "choice if the team is deeply AWS-native and the schema evolution requirement can be simplified.\n\n"
        "Azure Event Hubs is a viable alternative for Azure-centric organisations, but its lower skill-match score and "
        "Kafka compatibility edge cases make it the riskiest option for a team without existing Azure expertise."
    ),
    "consequences_positive": [
        "Schema Registry enforces schema evolution rules automatically, preventing breaking changes in production",
        "Large Kafka talent pool reduces hiring and onboarding risk",
        "200+ Kafka Connect connectors accelerate future source/sink integrations",
    ],
    "consequences_negative": [
        "Confluent Cloud creates vendor dependency for ksqlDB, Tiered Storage, and Schema Registry",
        "Cost may exceed $5,000/month if event volume scales beyond 3× current projections",
    ],
    "consequences_neutral": [
        "Team will need to monitor consumer group lag as part of ongoing operations",
        "Existing self-managed Kafka infrastructure (if any) can be migrated incrementally via MirrorMaker 2",
    ],
    "open_questions": [
        "What is the required message retention period — hours, days, or indefinite?",
        "Is exactly-once delivery required end-to-end, or is at-least-once delivery acceptable for IoT sensors?",
        "Does the team have an existing Confluent Cloud contract, or does a new commercial agreement need to be negotiated?",
    ],
}

_WRITER_TEMPLATE = """\
# ADR-0001: Streaming Platform for 10M IoT Events/Day

**Status:** Proposed
**Date:** {today}
**Deciders:** Platform team, IoT Engineering, Data Engineering
**Domain:** Data Platform

## Context and problem statement

We need to choose a streaming platform for processing 10 million IoT sensor events per day in real time,
with schema evolution support and a budget under $5,000/month.

## Decision drivers

- Low operational overhead
- High throughput at 10M events/day
- Schema evolution support (hard requirement)
- Cost efficiency under $5,000/month
- Real-time processing latency < 500ms

## Options considered

### Option 1: Apache Kafka on Confluent Cloud

Fully managed Kafka service with Schema Registry, ksqlDB, and 200+ connectors.
Provides exactly-once semantics and horizontal scalability for IoT event pipelines.

| Dimension | Score | Confidence | Rationale |
|---|---|---|---|
| Problem fit | 5 | high | Purpose-built for high-throughput streaming; Schema Registry meets the evolution constraint |
| Ecosystem maturity | 5 | high | De-facto standard with 10+ years of production use |
| Total cost of ownership | 4 | medium | $1,500–$3,000/month estimated at target scale |
| Operational overhead | 4 | high | Fully managed cluster, Schema Registry, and connectors |
| Risk and lock-in | 3 | high | Confluent-specific features create moderate dependency |
| Skill match | 4 | medium | Kafka expertise widely available |

**Weighted total:** 4.15 / 5.0

**Sources:**
1. https://docs.confluent.io/cloud/current/overview.html

---

### Option 2: AWS Kinesis Data Streams

Serverless AWS streaming service with on-demand scaling, deep Lambda/S3/Glue integration.

| Dimension | Score | Confidence | Rationale |
|---|---|---|---|
| Problem fit | 3 | high | Handles throughput; schema evolution requires separate Glue Schema Registry |
| Ecosystem maturity | 4 | high | Mature AWS service, narrower open-source ecosystem |
| Total cost of ownership | 5 | medium | $800–$1,500/month — most cost-effective option |
| Operational overhead | 5 | high | Fully serverless on-demand mode |
| Risk and lock-in | 2 | high | Deep AWS coupling; migration is costly |
| Skill match | 3 | medium | Kafka-experienced teams face Kinesis-specific learning curve |

**Weighted total:** 3.60 / 5.0

**Sources:**
1. https://docs.aws.amazon.com/streams/latest/dev/introduction.html

---

### Option 3: Azure Event Hubs

Managed event streaming with Kafka protocol compatibility and Azure Schema Registry.

| Dimension | Score | Confidence | Rationale |
|---|---|---|---|
| Problem fit | 3 | medium | Kafka surface API covers use case; schema evolution needs add-on |
| Ecosystem maturity | 4 | medium | Mature but Kafka compat has edge cases |
| Total cost of ownership | 3 | medium | $2,000–$3,500/month with Premium tier |
| Operational overhead | 3 | medium | Azure Schema Registry adds a separate management surface |
| Risk and lock-in | 3 | medium | Kafka compatibility reduces but does not eliminate lock-in |
| Skill match | 2 | medium | Best for Azure-native teams |

**Weighted total:** 3.05 / 5.0

**Sources:**
1. https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-about

---

## Decision

**Chosen option:** Apache Kafka on Confluent Cloud

Apache Kafka on Confluent Cloud scores highest overall (4.15/5.0) and best satisfies the primary
decision drivers. Its native Schema Registry directly addresses the schema evolution hard requirement,
and its maturity and ecosystem breadth reduce delivery and hiring risk.

AWS Kinesis offers lower cost and zero operational overhead, but schema evolution requires Glue Schema
Registry as a separate service — introducing integration complexity that conflicts with the low-overhead
driver.

Azure Event Hubs is a viable alternative for Azure-centric organisations, but its lower skill-match
score and Kafka compatibility edge cases make it the riskiest option for this team.

## Consequences

**Positive**
- Schema Registry enforces schema evolution rules automatically, preventing breaking changes in production
- Large Kafka talent pool reduces hiring and onboarding risk
- 200+ Kafka Connect connectors accelerate future source/sink integrations

**Negative / risks**
- Confluent Cloud creates vendor dependency for ksqlDB, Tiered Storage, and Schema Registry
- Cost may exceed $5,000/month if event volume scales beyond 3× current projections

**Neutral / notable**
- Team will need to monitor consumer group lag as part of ongoing operations
- Existing self-managed Kafka can be migrated incrementally via MirrorMaker 2

## Open questions

- [ ] What is the required message retention period — hours, days, or indefinite?
- [ ] Is exactly-once delivery required end-to-end, or is at-least-once acceptable for IoT sensors?
- [ ] Does the team have an existing Confluent Cloud contract, or does a new agreement need to be negotiated?

## References

1. https://docs.confluent.io/cloud/current/overview.html
2. https://docs.aws.amazon.com/streams/latest/dev/introduction.html
3. https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-about
"""


class MockLLMClient(LLMClient):
    """
    Deterministic LLM client for demo and testing.
    Dispatches to canned responses based on the system prompt.
    """

    def complete(self, messages: list[dict], system: str, max_tokens: int = 4096) -> str:
        system_lower = system.lower()
        user_content = messages[0]["content"] if messages else ""

        if "research assistant" in system_lower:
            return json.dumps([
                "Apache Kafka vs Kinesis streaming platform comparison 2025",
                "Confluent Cloud Schema Registry IoT event streaming",
                "AWS Kinesis Data Streams on-demand mode throughput limits",
                "Azure Event Hubs Kafka compatibility schema evolution",
                "streaming platform cost comparison 10 million events per day",
            ])

        if "intake parser" in system_lower:
            return json.dumps(_INTAKE)

        if "research synthesiser" in system_lower:
            return json.dumps(_RESEARCH)

        if "scoring engine" in system_lower:
            name_match = re.search(r'"option_name":\s*"([^"]+)"', user_content)
            key = name_match.group(1).lower() if name_match else ""
            scores = _SCORES.get(key, list(_SCORES.values())[0])
            return json.dumps(scores)

        if "clarification" in system_lower:
            return json.dumps([
                "Are you currently running any Kafka infrastructure, or would this be a greenfield deployment?",
                "Is your team primarily deployed on AWS, Azure, or GCP?",
                "Do you have an existing schema registry or data contract management solution?",
            ])

        if "reviewing a set of scored options" in system_lower:
            return json.dumps({
                "needs_retry": False,
                "options_needing_research": [],
                "suggested_queries": [],
            })

        if "decision analyst" in system_lower:
            return json.dumps(_DECISION)

        if "document writer" in system_lower:
            from datetime import date
            return _WRITER_TEMPLATE.format(today=date.today().isoformat())

        if "revising an architecture decision record" in system_lower:
            from datetime import date
            return _WRITER_TEMPLATE.format(today=date.today().isoformat())

        return "{}"
