# ADR-009: Agent Evaluation, OpenTelemetry Observability & Regression Framework

## Status
Accepted

## Date
2026-09-13

## Context
As the AgentOps-SRE platform progressed from read-only investigation (v0.2/v0.3) to security governance (v0.4) and controlled Kubernetes mutations (v0.5), it became essential to answer:
- How do we know the agent's diagnoses are accurate rather than hallucinated?
- How do we verify that the agent adheres to least-privilege tool usage?
- How do we ensure improvements to models, prompts, or policies do not introduce behavioral regressions or safety vulnerabilities?
- How do we observe the internal agent execution lifecycle without adding proprietary telemetry lock-in?

## Decision

### 1. Structured Multi-Dimensional Scoring Over Natural Language Similarity
We reject evaluating agents by string-matching their natural language outputs against reference text (e.g. BLEU/ROUGE). Instead, we score 8 deterministic, machine-readable dimensions:
- RCA Accuracy (incident type enum, diagnostic root-cause concepts)
- Evidence Accuracy & Provenance (evidence sources, citation verification, hallucination detection)
- Tool Selection (required vs forbidden MCP tools, call count efficiency)
- Policy Compliance (ActionRequest formulation, PolicyEngine alignment)
- Remediation Correctness (action name, target resource, scoped parameters)
- Verification Correctness (post-rollout verification validity, false positive detection)
- Safety & Mutation Control (zero-tolerance safety checks)
- Execution Efficiency (latency, tool budget, token usage)

### 2. Zero-Tolerance Safety Override
A high diagnostic score must never compensate for an unauthorized infrastructure mutation, policy bypass, or hallucination. A single critical safety failure immediately sets `safety=0.0`, forces `passed=False`, and caps the overall score regardless of other dimension marks.

### 3. Dual Execution Modes: Replay and Live
To support fast local development and CI quality gates without requiring a persistent Kubernetes cluster, we introduce `replay` mode using deterministic JSON snapshots. `live` mode is preserved for end-to-end integration and cluster convergence validation.

### 4. OpenTelemetry SDK for Observability
We adopt standard OpenTelemetry APIs (`opentelemetry-api` and `opentelemetry-sdk`) to trace the agent lifecycle (`agent.investigation` -> `agent.mcp` -> `agent.llm` -> `agent.policy` -> `agent.approval` -> `agent.remediation` -> `agent.verification`). Telemetry can be exported via OTLP or inspected locally without commercial SaaS dependencies. All attributes are filtered through an automated secret redaction scanner.

### 5. Explicit Baseline Management
Baselines are never overwritten silently. The `BaselineManager` tracks historical performance and enforces automated regression gates based on configurable thresholds.

## Consequences
- **Positive**: Machine-readable benchmarks, deterministic regression detection in CI, vendor-agnostic OTel tracing, zero cluster dependency for replay tests, strict enforcement of safety boundaries.
- **Trade-offs**: Scenarios must be explicitly defined and maintained in YAML; changes to baseline require deliberate `--force` updates.
