# AgentOps-SRE

> Production-style, local-first **AI SRE / AgentOps Platform** demonstrating safe, evidence-backed incident investigation, root-cause analysis (RCA), and policy-governed remediation on Kubernetes.

---

## Current Milestone: v0.3 (MCP Integration)

Milestone **v0.3** introduces the **Model Context Protocol (MCP)** as the standardized boundary between the AI SRE Agent and infrastructure investigation tools across Kubernetes, Prometheus, and Grafana Loki.

```
                     SRE Agent
                        │
                    MCP Client  (Discovers tools, invokes tool calls, tracks MCP metrics)
                        │
                  MCP / JSON-RPC (Standardized tool protocol)
                        │
                        ▼
                    MCP Server  (Validates schemas, routes requests, read-only guards)
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
     Kubernetes     Prometheus      Loki
        Tools          Tools        Tools
          │             │             │
          ▼             ▼             ▼
      Kubernetes    Prometheus     Grafana
         API           API          Loki
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
# Run unit tests (schemas, clients, models, security guards)
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
# Trigger incident
./scripts/trigger-incident.sh high-error-rate

# Run AI investigation via MCP
make investigate
# Or directly via CLI:
uv run python -m agentops.cli investigate --namespace demo --workload demo-app
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

### 4. Standalone MCP Server
```bash
# Run standalone MCP Server (stdio JSON-RPC transport)
uv run python -m agentops.cli mcp-server
```

### 5. Incident Recovery
```bash
./scripts/trigger-incident.sh reset
```

---

## Architecture Decisions & Documentation
- [docs/decisions/ADR-001-kind-for-local-kubernetes.md](docs/decisions/ADR-001-kind-for-local-kubernetes.md): Kind for Local Kubernetes
- [docs/decisions/ADR-002-alloy-over-promtail.md](docs/decisions/ADR-002-alloy-over-promtail.md): Grafana Alloy as Modern Log Collector
- [docs/decisions/ADR-003-read-only-investigation-and-isolation.md](docs/decisions/ADR-003-read-only-investigation-and-isolation.md): Read-Only Investigation Boundary & LLM Isolation
- [docs/decisions/ADR-004-mcp-as-tool-boundary.md](docs/decisions/ADR-004-mcp-as-tool-boundary.md): MCP as Standardized Tool Boundary
- [docs/architecture/v0.1-overview.md](docs/architecture/v0.1-overview.md): Infrastructure Foundation Overview
- [docs/architecture/v0.2-agent-architecture.md](docs/architecture/v0.2-agent-architecture.md): v0.2 AI SRE Agent Architecture
- [docs/architecture/v0.3-mcp-architecture.md](docs/architecture/v0.3-mcp-architecture.md): v0.3 MCP Integration Architecture & Schemas

---

## Teardown
```bash
make stop
```
