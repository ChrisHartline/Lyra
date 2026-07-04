---
name: system-refactoring
description: Plan and execute safe, incremental system modernization. Use for decomposition strategy, migration sequencing, risk control, and verification-first delivery.
disable-model-invocation: true
---

# System Refactoring

## Purpose
Modernize legacy systems safely through phased, verifiable changes that preserve behavior and reduce delivery risk.

## Scope
- Legacy risk assessment: coupling, debt, test gaps, operational bottlenecks
- Refactor patterns: strangler approach, parallel modernization, incremental extraction
- Migration execution: interface stabilization, data migration planning, rollout sequencing
- Verification: behavioral equivalence, regression testing, performance validation
- Target-state architecture: cloud-native, observable, scalable systems

## Workflow
1. Baseline current system behavior and critical paths.
2. Define bounded refactor slices with explicit rollback strategy.
3. Add missing test and observability coverage before migration.
4. Execute phased cutovers with production-safe checkpoints.
5. Retire legacy components only after parity and stability are proven.

## Default Output Shape
1. Risks and constraints
2. Refactor slices in priority order
3. Verification and testing strategy
4. Migration and rollback plan
5. Residual risk and follow-ups

## Guardrails
- Avoid big-bang rewrites unless explicitly required.
- Do not merge architecture changes without a verification path.
- Preserve domain behavior before pursuing stylistic cleanup.