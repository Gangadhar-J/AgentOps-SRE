# ADR-010: SRE Operator Console, REST API & Unified Incident Workflow

## Status
Accepted

## Date
2026-09-19

## Context
In previous milestones (v0.2–v0.6), AgentOps-SRE established an evidence-backed incident investigation engine, MCP tools, policy-governed security gateway, single-use human-in-the-loop approvals, controlled Kubernetes remediations, and reproducible evaluation gates.

However, operating the platform required remembering multiple low-level CLI commands and flags:
```bash
agentops investigate --namespace demo --workload demo-app ...
agentops remediate restart --namespace demo --deployment demo-app
agentops approvals list --pending
agentops approvals show <id>
agentops approvals approve <id> --operator ...
agentops remediate restart ... --approval-id <id>
```
During an on-call P1/P2 incident response at 2 AM, this introduces high cognitive load. An SRE thinks: *"demo-app is degraded. Investigate it and suggest a safe fix."*

Furthermore, operators require visual telemetry correlation, live cluster status, real-time pulse indicators, and visibility into local AI model runtimes (Ollama) without sacrificing any underlying security controls.

## Decision
We implement a first-class **SRE Operator Experience** consisting of:

1. **Web Operator Console (`agentops serve` / `make ui`)**:
   - Modern, lightweight browser interface served directly from the Python backend via Flask.
   - Distinct separation between **Real Mode** (live cluster diagnostics, Prometheus/Loki evidence, real workloads) and **Demo Playground** (synthetic chaos scenarios strictly isolated to sandbox targets).
   - Real-time **Telemetry Pulse** monitoring ready pods, restart counts, p95 latency, HTTP error rate, and memory usage with deep links to Prometheus and Grafana.
   - Provider-neutral **AI Runtime Observability** card displaying live local LLM inference latency, generation speed (tokens/sec), and token usage.

2. **AgentOps REST API**:
   - `/api/status`: Component connectivity (Kubernetes, Prometheus, Loki, Ollama, Eval Gate).
   - `/api/cluster/namespaces` & `/api/cluster/workloads`: Dynamic resource discovery.
   - `/api/telemetry/pulse`: Instant multi-signal cluster diagnostic snapshot.
   - `/api/llm/models`: Auto-discovery of local Ollama models and cloud providers.
   - `/api/incidents/investigate`: Single-entry autonomous investigation.
   - `/api/approvals/<id>/approve` & `reject`: Human-in-the-loop governance.
   - `/api/demo/trigger`: Strictly sandboxed chaos execution.

3. **Unified Incident Workflow & Simplified CLI**:
   - One-action command: `agentops incident <namespace>/<workload>` (or `agentops run`).
   - Handles the entire flow: Telemetry Gathering → LLM RCA → Policy Evaluation → Human Approval → Single-Use Token Execution → Post-Remediation Verification.

4. **Preserved Security Invariants**:
   - The UI and REST API must **never** bypass the security chain:
     `ActionRequest -> PolicyEngine -> ApprovalManager -> SecurityGateway -> Controlled Remediation -> Post-Verification`
   - The `SecurityGateway` remains the single authorized mutator. Single-use replay protection and request binding are strictly enforced.

## Consequences

### Positive
- Drastically reduced mean time to investigate (MTTI) and cognitive load for on-call SREs.
- Operators can seamlessly choose between local Ollama models (e.g., `granite4.1:3b`, `qwen3.5:2b`, `ministral-3:8b`), cloud providers, or fast deterministic rule engines.
- Full transparency with live inference speed and token tracking.
- Post-remediation verification guarantees mutations are validated for actual workload health before marking an incident resolved.

### Negative / Trade-offs
- Adds Flask and web asset serving to the core CLI footprint.
- Requires running background server process for the browser UI.
