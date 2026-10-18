# AgentOps-SRE

> Production-style, local-first **AI SRE / AgentOps Platform** demonstrating safe, evidence-backed incident investigation, root-cause analysis (RCA), policy governance, human-in-the-loop approval, and controlled Kubernetes remediation.

---

## Current Release: v0.7.2 (Real AI Enforcement, Security Hardening & Unified Observability Console)

**AgentOps-SRE v0.7.2** represents a comprehensive hardening and observability release:

- **🚫 Real AI Enforcement**: Completely eliminated mock and deterministic RCA generation from all live investigation paths. Real LLMs (Ollama local models or configured Cloud providers) are strictly required for operational analysis.
- **🛡️ Typed Error Taxonomy**: Stable error taxonomy (`LLMError`, `ProviderUnavailableError`, `ModelNotFoundError`, `InferenceTimeoutError`, `InvalidModelOutputError`, `EvidenceValidationError`, `ProviderAuthenticationError`, `RateLimitError`) mapping provider failures into transparent diagnostic records.
- **🔎 Evidence Reference Validation**: Independent verification of model claims against ground-truth evidence items (`context.evidence_items`). Hallucinated or unsupported evidence IDs are rejected before reaching policy evaluation.
- **🔒 Fail-Closed Security Invariant**: Failed inference, unvalidated RCAs, or unknown incident types never create actionable approvals. Unknown remediation actions fail closed (`action="none"`).
- **🌐 Portable Configuration**: Dynamic `pathlib.Path` resolution, `KUBECONFIG` environment variable discovery, zero hardcoded developer paths, and default binding strictly to `127.0.0.1:8000`.
- **🖥️ Unified 8-Section Operator Console**: Pure vanilla JavaScript and modern dark-mode CSS (zero npm or Node.js dependencies) running across 8 dedicated operational sections:
  1. **📊 Overview**: Cluster infrastructure, telemetry health, live pulse, and latest incident snapshot.
  2. **☸️ Cluster & Workloads**: Live topology, nodes conditions table, workload pod replicas, and warning events stream.
  3. **🔍 Incident Investigation**: Multi-signal evidence collection, real LLM root cause analysis, grounded evidence pills, policy governance, and inline approval execution.
  4. **🤖 LLM Observability**: 9-step visual lifecycle stepper (Configured → Reachable → Discovered → Selected → Invoked → Inference Done → Schema Valid → Evidence Grounded → Completed), inference latency, token metrics, generation speed (tok/s), and execution history table.
  5. **🔎 Evidence Explorer**: Filterable multi-signal evidence cards across Kubernetes, Prometheus, and Loki with direct cross-linking.
  6. **🛡️ Approvals & Remediation**: Human-in-the-loop authorization cards, single-use token consumption, and post-remediation rollout verification.
  7. **📈 Evaluation & Regression**: Deterministic offline benchmark replay engine (v0.6), quality gate scoring (96.5%), and baseline regression tracking.
  8. **🩺 Platform Diagnostics**: Real-time health matrix for Kubernetes API, Prometheus, Loki, Grafana, Ollama, and OpenTelemetry tracing.
- **⚡ Isolated Demo Chaos Sandbox**: Modal playground strictly restricted to sandbox workload `demo/demo-app` (`crashloop`, `high-error-rate`, `resource-exhaustion`, `bad-deployment`, `reset`).

```text
                         ┌──────────────────────────────────────────────┐
                         │   SRE Operator (Unified 8-Section Console)   │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │              AgentOps REST API               │
                         │         (/api/incidents/investigate)         │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │                  SRE Agent                   │
                         │        (Evidence Collection via MCP)         │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │             Real LLM Reasoning               │
                         │        (Local Ollama / Cloud Providers)      │
                         │    [Strict Schema & Evidence Validation]     │
                         └──────────────────────┬───────────────────────┘
                                                │
                                          ActionRequest
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │                Policy Engine                 │
                         └──────────────────────┬───────────────────────┘
                                                │
                                        REQUIRE_APPROVAL
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │           Approval Manager (HITL)            │
                         │          (Single-Use Approval Token)         │
                         └──────────────────────┬───────────────────────┘
                                                │
                                             APPROVED
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │               Security Gateway               │
                         │       1. Re-validate Live State              │
                         │       2. Pre-Remediation Snapshot            │
                         │       3. Single-Use Token Consumption        │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │             Controlled Mutation              │
                         │        (restart / scale / rollback)          │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │        Post-Remediation Verification         │
                         │       - Rollout Convergence Check            │
                         │       - Pod Readiness & Health Check         │
                         └──────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Prerequisites
- macOS (Apple Silicon or Intel) or Linux
- Docker Desktop / daemon running
- `kind`, `kubectl`, `uv` (or `python3` / `pip`), `make`
- [Ollama](https://ollama.com) running on `http://127.0.0.1:11434` with at least one model pulled (e.g., `ollama pull qwen3.5:2b` or `ollama pull granite4.1:3b`)

### 2. Launch Environment
```bash
# Verify environment dependencies
make preflight

# Create Kind cluster, deploy observability stack (Prometheus, Grafana, Loki, Alloy) & demo app
make setup

# Check status of cluster and pods
make status
```

### 3. Launch the Unified Operator Console (Web UI)
```bash
# Start the web console & REST API server
make ui
# or: make serve
```
Open **`http://127.0.0.1:8000`** in your browser to access the 8-section console.

---

## Unified Incident Workflow (CLI)

For command-line incident investigation and remediation:

```bash
# Run one-action autonomous investigation & recommendation
make incident
# or:
uv run python -m agentops.cli incident demo/demo-app

# Run with dry-run mode (evaluates policy & risk without creating approval)
uv run python -m agentops.cli incident demo/demo-app --dry-run

# Run with a specific local Ollama model
uv run python -m agentops.cli incident demo/demo-app --provider ollama --model granite4.1:3b

# Authorize and execute pending remediation in one step
uv run python -m agentops.cli incident demo/demo-app --auto-approve --operator sre-oncall
```

---

## REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/status` | `GET` | Live connectivity status for K8s, Prometheus, Loki, Grafana, Ollama, and Eval Gate |
| `/api/cluster/overview` | `GET` | Cluster context, auth mode, node count, and real node status table |
| `/api/cluster/namespaces` | `GET` | Dynamically discover real cluster namespaces |
| `/api/cluster/workloads?namespace=<ns>` | `GET` | List deployments in the specified namespace |
| `/api/cluster/pods?namespace=<ns>&workload=<wl>` | `GET` | Retrieve live pod replicas with phase, restarts, and condition reasons |
| `/api/cluster/events?namespace=<ns>&workload=<wl>` | `GET` | Retrieve recent warning events for the target workload |
| `/api/telemetry/pulse?namespace=<ns>&workload=<wl>` | `GET` | Real-time multi-signal telemetry pulse with deep links |
| `/api/llm/models` | `GET` | Auto-discover local Ollama models and configured cloud providers |
| `/api/llm/history` | `GET` | Session history of executed LLM inferences with latency, tokens, and validation status |
| `/api/incidents/investigate` | `POST` | Execute autonomous incident investigation and policy evaluation |
| `/api/incidents/active` | `GET` | Retrieve current in-memory active incident report |
| `/api/approvals/pending` | `GET` | List all pending human approval requests |
| `/api/approvals/<id>/approve` | `POST` | Authorize and execute controlled remediation via SecurityGateway |
| `/api/approvals/<id>/reject` | `POST` | Reject proposed remediation |
| `/api/demo/trigger` | `POST` | Trigger sandboxed chaos scenarios (`demo/demo-app` only) |
| `/api/eval/summary` | `GET` | Retrieve latest benchmark evaluation scores |

---

## Reproducing Incidents & Chaos Scenarios

You can trigger reproducible incidents against the demo application:

```bash
# 1. High HTTP 500 Error Rate
./scripts/trigger-incident.sh high-error-rate

# 2. CrashLoopBackOff
./scripts/trigger-incident.sh crashloop

# 3. Resource Exhaustion (Memory leak leading to OOMKilled)
./scripts/trigger-incident.sh resource-exhaustion

# 4. Bad Deployment Revision (ImagePullBackOff)
./scripts/trigger-incident.sh bad-deployment

# 5. Restore Demo Application to Healthy State
./scripts/trigger-incident.sh reset
```

---

## Agent Evaluation & Regression Quality Gate (v0.6 Engine)

```bash
# 1. Run evaluation on a single scenario (replay mode)
uv run python -m agentops.cli eval run --scenario crashloop-001 --mode replay

# 2. Run full benchmark suite across all scenarios
uv run python -m agentops.cli eval run --all --mode replay --provider mock

# 3. Explicitly save current run as evaluation baseline
uv run python -m agentops.cli eval baseline save --mode replay --provider mock --force

# 4. CI Quality Gate (evaluates scenarios, checks against baseline, exits non-zero on regression)
uv run python -m agentops.cli eval gate --mode replay --provider mock

# 5. Convenient Make targets
make eval          # Run default scenario evaluation
make eval-all      # Run all benchmark evaluations
make eval-baseline # Update baseline record
make eval-gate     # Automated CI quality gate
```

---

## Running Automated Tests

```bash
# Run unit tests (133 tests: schemas, security, policy, gateway, API, workflows, real AI enforcement)
make test

# Run API & Operator console tests
make test-api

# Run infrastructure & MCP pipeline integration tests (requires live Kind cluster)
make test-infra

# Run end-to-end incident investigation scenarios against live cluster
make test-scenarios

# Run all test suites
make test-all
```

---

## Architecture Decisions & Documentation

- [docs/decisions/ADR-001-kind-for-local-kubernetes.md](docs/decisions/ADR-001-kind-for-local-kubernetes.md): Kind for Local Kubernetes
- [docs/decisions/ADR-002-alloy-over-promtail.md](docs/decisions/ADR-002-alloy-over-promtail.md): Grafana Alloy as Modern Log Collector
- [docs/decisions/ADR-003-read-only-investigation-and-isolation.md](docs/decisions/ADR-003-read-only-investigation-and-isolation.md): Read-Only Investigation Boundary & LLM Isolation
- [docs/decisions/ADR-004-mcp-as-tool-boundary.md](docs/decisions/ADR-004-mcp-as-tool-boundary.md): MCP as Standardized Tool Boundary
- [docs/decisions/ADR-005-agent-identity-and-capability-model.md](docs/decisions/ADR-005-agent-identity-and-capability-model.md): Agent Identity and Capability-Based Security Model
- [docs/decisions/ADR-006-policy-engine-and-security-gateway.md](docs/decisions/ADR-006-policy-engine-and-security-gateway.md): Policy Engine and Authorizing Security Gateway
- [docs/decisions/ADR-007-human-in-the-loop-approval.md](docs/decisions/ADR-007-human-in-the-loop-approval.md): Human-in-the-Loop Approval Workflow and Replay Protection
- [docs/decisions/ADR-008-controlled-kubernetes-remediation.md](docs/decisions/ADR-008-controlled-kubernetes-remediation.md): Controlled Kubernetes Remediation & Post-Execution Verification
- [docs/decisions/ADR-009-agent-evaluation-framework.md](docs/decisions/ADR-009-agent-evaluation-framework.md): Agent Evaluation, OpenTelemetry Observability & Regression Framework
- [docs/decisions/ADR-010-sre-operator-console-and-api.md](docs/decisions/ADR-010-sre-operator-console-and-api.md): SRE Operator Console, REST API & Unified Incident Workflow
- [docs/architecture/v0.1-overview.md](docs/architecture/v0.1-overview.md): Infrastructure Foundation Overview
- [docs/architecture/v0.2-agent-architecture.md](docs/architecture/v0.2-agent-architecture.md): v0.2 AI SRE Agent Architecture
- [docs/architecture/v0.3-mcp-architecture.md](docs/architecture/v0.3-mcp-architecture.md): v0.3 MCP Integration Architecture & Schemas
- [docs/architecture/v0.4.3-policy-gateway.md](docs/architecture/v0.4.3-policy-gateway.md): v0.4.3 Policy Engine & Security Gateway
- [docs/architecture/v0.4.4-human-approval.md](docs/architecture/v0.4.4-human-approval.md): v0.4.4 Human Approval Architecture
- [docs/architecture/v0.5-controlled-remediation.md](docs/architecture/v0.5-controlled-remediation.md): v0.5 Controlled Remediation Architecture
- [docs/architecture/v0.6-evaluation-observability.md](docs/architecture/v0.6-evaluation-observability.md): v0.6 Agent Evaluation & Observability Architecture
- [docs/architecture/v0.7-operator-experience.md](docs/architecture/v0.7-operator-experience.md): v0.7 / v0.7.1 SRE Operator Console & REST API Architecture

---

## Teardown
```bash
make stop
```
