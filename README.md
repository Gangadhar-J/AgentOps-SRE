# AgentOps-SRE

> Production-style, local-first **AI SRE / AgentOps Platform** demonstrating safe, evidence-backed incident investigation, root-cause analysis (RCA), policy governance, human-in-the-loop approval, and controlled Kubernetes remediation.

---

## Current Milestone: v0.6 (Evaluation, Observability & Regression Framework)

Milestone **v0.6** introduces the **Agent Evaluation, OpenTelemetry Observability & Regression Framework**, establishing structured multi-dimensional evaluation, automated regression quality gates, reproducible YAML benchmarks, and standardized OpenTelemetry lifecycle tracing.

```
                         ┌─────────────────────┐
                         │      SRE Agent      │
                         └──────────┬──────────┘
                                    │
                              ActionRequest  (action, target, reason, evidence_refs)
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │    Policy Engine    │
                         └──────────┬──────────┘
                                    │
                           REQUIRE_APPROVAL
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Human Approval     │
                         └──────────┬──────────┘
                                    │
                                APPROVED
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Security Gateway    │
                         │                     │
                         │ 1. Re-validate      │
                         │ 2. Pre-Snapshot     │
                         │ 3. Single-use Bind  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │     MCP Server      │
                         │                     │
                         │ • restart_deploy    │
                         │ • scale_deploy      │
                         │ • rollback_deploy   │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Kubernetes API     │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Post-Verification   │
                         │                     │
                         │ • Rollout Complete  │
                         │ • Pods Ready        │
                         │ • Replicas Match    │
                         └─────────────────────┘
```

---

## Quick Start

### 1. Prerequisites
- macOS (Apple Silicon or Intel)
- Docker Desktop (running)
- `kind`, `kubectl`, `uv` (or `python3` / `pip`), `make`

### 2. Launch Environment
```bash
# Verify environment dependencies
make preflight

# Create Kind cluster, deploy observability stack & demo app
make setup

# Check status of cluster and pods
make status
```

### 3. Run Automated Tests
```bash
# Run unit tests (schemas, clients, security models, policy engine, approvals, remediation)
make test

# Run infrastructure & MCP pipeline integration tests
make test-infra

# Run end-to-end incident investigation scenarios via MCP against live cluster
make test-scenarios

# Run all test suites
make test-all
```

---

## Investigating Incidents with the AI SRE Agent (over MCP)

You can trigger reproducible incidents and run the investigation agent through MCP:

### 1. High HTTP 500 Error Rate
```bash
./scripts/trigger-incident.sh high-error-rate
make investigate
```

### 2. CrashLoopBackOff
```bash
./scripts/trigger-incident.sh crashloop
make investigate
```

### 3. Resource Exhaustion (OOMKilled)
```bash
./scripts/trigger-incident.sh resource-exhaustion
make investigate
```

### 4. Incident Recovery
```bash
./scripts/trigger-incident.sh reset
```

---

## Human Operator Approvals Workflow (CLI)

```bash
# List all pending approval requests
uv run python -m agentops.cli approvals list --pending

# Inspect a specific approval request
uv run python -m agentops.cli approvals show <approval-id>

# Approve a request
uv run python -m agentops.cli approvals approve <approval-id> --operator alice.sre --reason "Verified CrashLoopBackOff via E001"

# Reject a request
uv run python -m agentops.cli approvals reject <approval-id> --operator alice.sre --reason "Incident already mitigated"
```

---

## Controlled Remediation CLI Workflow

```bash
# 1. Dry-run remediation validation
uv run python -m agentops.cli remediate restart --namespace demo --deployment demo-app --dry-run

# 2. Execute approved rolling restart
uv run python -m agentops.cli remediate restart --namespace demo --deployment demo-app --approval-id <approval-id>

# 3. Controlled horizontal scaling
uv run python -m agentops.cli remediate scale --namespace demo --deployment demo-app --replicas 3 --approval-id <approval-id>

# 4. Controlled rollback to revision
uv run python -m agentops.cli remediate rollback --namespace demo --deployment demo-app --revision 1 --approval-id <approval-id>
```

---
 
## Agent Evaluation & Regression Framework (v0.6 CLI)

```bash
# 1. Run evaluation on a single scenario (fast replay mode)
uv run python -m agentops.cli eval run --scenario crashloop-001 --mode replay

# 2. Run full benchmark suite across all scenarios
uv run python -m agentops.cli eval run --all --mode replay --provider mock

# 3. Explicitly save current run as evaluation baseline
uv run python -m agentops.cli eval baseline save --mode replay --provider mock --force

# 4. CI Quality Gate (evaluates scenarios, checks against baseline, exits non-zero on regression)
uv run python -m agentops.cli eval gate --mode replay --provider mock

# 5. Make targets for CI/CD
make eval          # Run default scenario evaluation
make eval-all      # Run all benchmark evaluations
make eval-baseline # Update baseline record
make eval-gate     # Automated CI quality gate
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
- [docs/architecture/v0.1-overview.md](docs/architecture/v0.1-overview.md): Infrastructure Foundation Overview
- [docs/architecture/v0.2-agent-architecture.md](docs/architecture/v0.2-agent-architecture.md): v0.2 AI SRE Agent Architecture
- [docs/architecture/v0.3-mcp-architecture.md](docs/architecture/v0.3-mcp-architecture.md): v0.3 MCP Integration Architecture & Schemas
- [docs/architecture/v0.4.3-policy-gateway.md](docs/architecture/v0.4.3-policy-gateway.md): v0.4.3 Policy Engine & Security Gateway
- [docs/architecture/v0.4.4-human-approval.md](docs/architecture/v0.4.4-human-approval.md): v0.4.4 Human Approval Architecture
- [docs/architecture/v0.5-controlled-remediation.md](docs/architecture/v0.5-controlled-remediation.md): v0.5 Controlled Remediation Architecture
- [docs/architecture/v0.6-evaluation-observability.md](docs/architecture/v0.6-evaluation-observability.md): v0.6 Agent Evaluation & Observability Architecture

---

## Teardown
```bash
make stop
```
