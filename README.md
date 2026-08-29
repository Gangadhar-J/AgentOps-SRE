# AgentOps-SRE

> Production-style, local-first **AI SRE / AgentOps Platform** demonstrating safe, evidence-backed incident investigation, root-cause analysis (RCA), and policy-governed remediation on Kubernetes.

---

## Current Milestone: v0.2 (Basic AI SRE Agent)

Milestone **v0.2** introduces an AI-assisted SRE investigation system that collects telemetry across **Kubernetes**, **Prometheus**, and **Grafana Loki**, structures the multi-modal evidence into an immutable provenance model (`E001`, `E002`...), and synthesizes a structured Root Cause Analysis (RCA) JSON report.

```
                 Incident Alert / Investigation Request
                                    │
                                    ▼
                          ┌──────────────────┐
                          │     SREAgent     │  (Tracks execution duration,
                          └─────────┬────────┘   queries, tokens, latency)
                                    │
                                    ▼
                   ┌─────────────────────────────────┐
                   │   Investigation Orchestrator    │
                   └────────────────┬────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
            ▼                       ▼                       ▼
   ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
   │ Kubernetes API  │     │   Prometheus    │     │   Grafana Loki  │
   │  Client (READ)  │     │  Client (READ)  │     │  Client (READ)  │
   └────────┬────────┘     └────────┬────────┘     └────────┬────────┘
            │                       │                       │
            └───────────────────────┼───────────────────────┘
                                    │
                                    ▼
                         ┌────────────────────┐
                         │   Evidence Model   │  (FACT vs INFERENCE vs HYPOTHESIS)
                         └──────────┬─────────┘
                                    │
                                    ▼
                         ┌────────────────────┐
                         │    LLM Provider    │  (Provider-agnostic interface:
                         │   (RCA Generator)  │   Gemini, OpenAI, Mock/Heuristic)
                         └──────────┬─────────┘
                                    │
                                    ▼
                         ┌────────────────────┐
                         │   Structured RCA   │  (Evidence-backed, confidence,
                         │    (JSON Model)    │   recommendations, audit timeline)
                         └────────────────────┘
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
# Run unit tests (models, clients, security boundaries)
make test

# Run infrastructure integration tests against the live cluster
make test-infra

# Run end-to-end incident investigation scenarios against live cluster
make test-scenarios

# Run all test suites
make test-all
```

---

## Investigating Incidents with the AI SRE Agent

You can trigger reproducible incidents and run the investigation agent via the CLI:

### 1. High HTTP 500 Error Rate
```bash
# Trigger incident
./scripts/trigger-incident.sh high-error-rate

# Run AI investigation
make investigate
# Or via CLI:
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

### 4. Incident Recovery
```bash
./scripts/trigger-incident.sh reset
```

---

## Architecture Decisions & Documentation
- [docs/decisions/ADR-001-kind-for-local-kubernetes.md](docs/decisions/ADR-001-kind-for-local-kubernetes.md): Kind for Local Kubernetes
- [docs/decisions/ADR-002-alloy-over-promtail.md](docs/decisions/ADR-002-alloy-over-promtail.md): Grafana Alloy as Modern Log Collector
- [docs/decisions/ADR-003-read-only-investigation-and-isolation.md](docs/decisions/ADR-003-read-only-investigation-and-isolation.md): Read-Only Investigation Boundary & LLM Isolation
- [docs/architecture/v0.1-overview.md](docs/architecture/v0.1-overview.md): Infrastructure Foundation Overview
- [docs/architecture/v0.2-agent-architecture.md](docs/architecture/v0.2-agent-architecture.md): v0.2 AI SRE Agent Architecture & Schemas

---

## Teardown
```bash
make stop
```
