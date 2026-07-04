---
name: gcp-enterprise-networking
description: Design and troubleshoot enterprise-grade GCP networking architectures. Use for VPC, hybrid connectivity, segmentation, security controls, and operational hardening.
disable-model-invocation: true
---

# GCP Enterprise Networking

## Purpose
Deliver secure, observable, and scalable network architectures on GCP for enterprise workloads.

## Scope
- Foundational networking: Shared VPC, peering, Cloud NAT, Cloud Router, Cloud DNS, load balancing
- Enterprise patterns: hub-and-spoke, mesh, micro-segmentation, Private Service Connect
- Security and compliance: hierarchical firewalls, Cloud Armor, VPC Service Controls, certificate policy
- Observability: flow logs, firewall logs, packet mirroring, Network Intelligence Center
- AI-era networking: low-latency designs for AI/ML workloads and IPv6 adoption planning

## Workflow
1. Capture current topology, constraints, and compliance requirements.
2. Identify primary risks (routing, segmentation, IAM, egress, DNS).
3. Produce target architecture with phased rollout plan.
4. Define validation checks (connectivity, latency, policy, logging).
5. Recommend hardening and operations runbook updates.

## Default Output Shape
1. Assumptions and constraints
2. Current-state risks
3. Target architecture recommendation
4. Implementation plan
5. Verification and guardrails

## Guardrails
- Do not recommend public exposure where private connectivity is feasible.
- Prefer least privilege and explicit deny behavior.
- Favor IaC-backed changes and rollback-ready rollout plans.