# AgentOps-SRE

> Production-style, local-first **AI SRE / AgentOps Platform** demonstrating safe, evidence-backed incident investigation, root-cause analysis (RCA), policy governance, human-in-the-loop approval, and controlled Kubernetes remediation.

---

## Current Milestone: v0.7.1 (SRE Real Operator Console & Unified Incident Workflow)

Milestone **v0.7 / v0.7.1** transforms AgentOps-SRE into a complete, human-centered **SRE Operator Experience**:
- **🖥️ SRE Real Operator Console**: Modern dark-mode web console running at `http://127.0.0.1:8000` with live cluster diagnostics and strictly isolated chaos sandbox.
- **📡 Live Telemetry Pulse**: Instant multi-signal cluster diagnostic snapshot (ready pods, restart counts, p95 latency, HTTP 500 error rates, memory usage, warning events) with direct deep links to Prometheus and Grafana.
- **🦙 Provider-Neutral Local AI Runtime**: Dynamic discovery of local Ollama models (`granite4.1:3b`, `qwen3.5:2b`, `ministral-3:8b`, etc.), Cloud LLMs (Gemini, OpenAI), and deterministic rule engines with live inference latency, generation speed (tok/s), and token usage telemetry.
- **⚡ Unified Incident Workflow**: One-action investigation-to-remediation command (`agentops incident <ns>/<workload>`) eliminating cognitive load while preserving 100% of the underlying policy and security invariants.
- **🛡️ Mandatory Security Boundary**: All mutations strictly routed through `ActionRequest` → `PolicyEngine` → `ApprovalManager` → `SecurityGateway` → `Post-Verification`.

```
                         ┌──────────────────────────────────────────────┐
                         │   SRE Operator (Web Console / Unified CLI)   │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │               AgentOps REST API              │
                         │          (/api/incidents/investigate)        │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │                  SRE Agent                   │
                         │       (Evidence Collection over MCP)         │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │           AI Model Reasoning (RCA)           │
                         │    (Local Ollama / Cloud LLM / Rule Engine)  │
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
                         │            Approval Manager (HITL)           │
                         │           (Single-Use Approval Token)        │
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
                         │       (restart / scale / rollback)           │
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
- *(Optional)* [Ollama](https://ollama.com) running locally on `:11434` for local AI models

### 2. Launch Environment
```bash
# Verify environment dependencies
make preflight

# Create Kind cluster, deploy observability stack (Prometheus, Grafana, Loki, Alloy) & demo app
make setup

# Check status of cluster and pods
make status
```

### 3. Launch the SRE Operator Console (Web UI)
```bash
# Start the web console & REST API server
make ui
# or: make serve
```
Open **`http://127.0.0.1:8000`** in your browser to access:
- **🔍 Real Incident Investigation**: Select any active namespace, workload, and AI model to run live diagnostics.
- **📡 Live Telemetry Pulse**: Real-time pod readiness, error rates, p95 latency, and warnings.
- **🧪 Demo Playground**: Sandbox chaos tests (`crashloop`, `high-error-rate`, `resource-exhaustion`, `bad-deployment`, `reset`).
- **✅ Approval Action Bar**: One-click authorization with single-use replay protection.

---

## Unified Incident Workflow (CLI)

For command-line response during active incidents:

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
| `/api/status` | `GET` | Live connectivity status for K8s, Prometheus, Loki, Ollama, and Eval Gate |
| `/api/cluster/namespaces` | `GET` | Dynamically discover cluster namespaces |
| `/api/cluster/workloads?namespace=<ns>` | `GET` | List deployments in the specified namespace |
| `/api/telemetry/pulse?namespace=<ns>&workload=<wl>` | `GET` | Real-time multi-signal telemetry pulse with deep links |
| `/api/llm/models` | `GET` | Auto-discover local Ollama models and configured providers |
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

## Agent Evaluation & Regression Quality Gate (v0.6)

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
# Run unit tests (120 tests: schemas, security, policy, gateway, API, workflows)
make test

# Run API & Operator console tests
make test-api

# Run infrastructure & MCP pipeline integration tests
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
