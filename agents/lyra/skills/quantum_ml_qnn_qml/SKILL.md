---
name: quantum-ml-qnn-qml
description: Guide quantum machine learning workflows with practical hybrid strategies. Use for QNN/QML architecture choices, experiment design, and realistic benchmark-driven recommendations.
disable-model-invocation: true
---

# Quantum ML / QNN / QML

## Purpose
Provide practical, benchmark-oriented guidance for quantum machine learning with strong emphasis on hybrid near-term value.

## Scope
- QNN and QML fundamentals: VQCs, PQCs, kernels, and feature maps
- Hybrid architecture design: classical + quantum pipeline composition
- Experimentation strategy: baselines, metrics, ablation, reproducibility
- Platform selection: Cirq, Qiskit, PennyLane, and managed quantum options
- Risk handling: noise mitigation, barren plateaus, feasibility constraints

## Workflow
1. Determine if the problem is quantum-suitable versus classical-first.
2. Define baseline classical model and fair comparison criteria.
3. Propose candidate hybrid quantum architectures.
4. Specify experiment plan, metrics, and reproducibility controls.
5. Recommend go/no-go based on measured advantage.

## Default Output Shape
1. Suitability assessment
2. Candidate architectures
3. Experiment plan
4. Benchmark and evaluation criteria
5. Risks, limits, and decision guidance

## Guardrails
- Do not claim quantum advantage without explicit benchmarks.
- Keep expectations grounded in NISQ-era constraints.
- Prefer reproducible hybrid workflows over speculative designs.