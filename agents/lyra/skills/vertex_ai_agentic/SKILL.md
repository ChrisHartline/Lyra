---
name: vertex-ai-agentic
description: Architect and operationalize agentic systems on Vertex AI. Use for orchestration, tool integration, evaluation, safety, and production deployment patterns.
disable-model-invocation: true
---

# Vertex AI Agentic

## Purpose
Build reliable, observable, and production-grade agent workflows using Vertex AI and adjacent tooling.

## Scope
- Vertex AI platform usage: Agent Builder, Pipelines, Model Garden, Vector Search, model lifecycle
- Agent architecture: single-agent and multi-agent orchestration, tool calling, memory patterns
- Reliability and safety: evaluation, guardrails, grounding strategies, human-in-the-loop controls
- Operations: monitoring, logging, cost controls, and incident-friendly observability
- Integrations: MCP-connected tools and secure GCP service access

## Workflow
1. Clarify use case, latency/cost limits, and failure tolerance.
2. Choose minimal viable agent architecture and tool boundaries.
3. Define evaluation harness and safety constraints before scale-up.
4. Implement deployment and observability strategy.
5. Iterate with measured quality/cost/reliability feedback loops.

## Default Output Shape
1. Use-case framing and constraints
2. Recommended architecture
3. Implementation plan
4. Evaluation and safety plan
5. Operational checklist

## Guardrails
- Avoid recursive complexity without explicit operational need.
- Treat tool outputs as untrusted until validated.
- Require measurable eval criteria for any production recommendation.