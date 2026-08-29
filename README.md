# AgentOps-SRE

> Production-style, local-first **AI SRE / AgentOps Platform** demonstrating safe, evidence-backed incident investigation, root-cause analysis (RCA), policy governance, and human-in-the-loop remediation on Kubernetes.

---

## Current Milestone: v0.4.4 (Human-in-the-Loop Approval Workflow)

Milestone **v0.4.4** implements the **Human-in-the-Loop Approval Workflow**, enabling safe operator authorization, time-to-live expiration, request binding, and single-use replay protection for remediation actions.

```
                    SRE Agent
                       │
                 ActionRequest  (action, target, reason, evidence_refs)
                       │
                       ▼
               Security Gateway
                       │
                       ▼
                 Policy Engine   (Evaluates policy -> REQUIRE_APPROVAL)
                       │
                       ▼
                ApprovalManager  (Creates ApprovalRequest, status=PENDING, TTL=900s)
                       │
                       ▼
              SQLite Storage (data/agentops.db)
                       │
                       ▼
                 Human Operator  (agentops approvals approve <id> --operator alice.sre)
                       │
                       ▼
                Status: APPROVED
                       │
                       ▼
               Security Gateway  (execute_approved_action)
                       ├── 1. Check approval is APPROVED and NOT expired
                       ├── 2. Verify exact request binding (action, target, evidence)
                       ├── 3. Re-evaluate live policy & capabilities
                       ├── 4. Transition status: APPROVED -> CONSUMED
                       └── 5. Execute safe callback
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
# Run unit tests (schemas, clients, security models, policy engine, approvals)
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

## Architecture Decisions & Documentation
- [docs/decisions/ADR-001-kind-for-local-kubernetes.md](docs/decisions/ADR-001-kind-for-local-kubernetes.md): Kind for Local Kubernetes
- [docs/decisions/ADR-002-alloy-over-promtail.md](docs/decisions/ADR-002-alloy-over-promtail.md): Grafana Alloy as Modern Log Collector
- [docs/decisions/ADR-003-read-only-investigation-and-isolation.md](docs/decisions/ADR-003-read-only-investigation-and-isolation.md): Read-Only Investigation Boundary & LLM Isolation
- [docs/decisions/ADR-004-mcp-as-tool-boundary.md](docs/decisions/ADR-004-mcp-as-tool-boundary.md): MCP as Standardized Tool Boundary
- [docs/decisions/ADR-005-agent-identity-and-capability-model.md](docs/decisions/ADR-005-agent-identity-and-capability-model.md): Agent Identity and Capability-Based Security Model
- [docs/decisions/ADR-006-policy-engine-and-security-gateway.md](docs/decisions/ADR-006-policy-engine-and-security-gateway.md): Policy Engine and Authorizing Security Gateway
- [docs/decisions/ADR-007-human-in-the-loop-approval.md](docs/decisions/ADR-007-human-in-the-loop-approval.md): Human-in-the-Loop Approval Workflow and Replay Protection
- [docs/architecture/v0.1-overview.md](docs/architecture/v0.1-overview.md): Infrastructure Foundation Overview
- [docs/architecture/v0.2-agent-architecture.md](docs/architecture/v0.2-agent-architecture.md): v0.2 AI SRE Agent Architecture
- [docs/architecture/v0.3-mcp-architecture.md](docs/architecture/v0.3-mcp-architecture.md): v0.3 MCP Integration Architecture & Schemas
- [docs/architecture/v0.4.3-policy-gateway.md](docs/architecture/v0.4.3-policy-gateway.md): v0.4.3 Policy Engine & Security Gateway
- [docs/architecture/v0.4.4-human-approval.md](docs/architecture/v0.4.4-human-approval.md): v0.4.4 Human Approval Architecture

---

## Teardown
```bash
make stop
```
