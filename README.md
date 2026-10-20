# AgentOps-SRE

> Production-style, local-first **AI SRE / AgentOps Platform** demonstrating safe, evidence-backed incident investigation, root-cause analysis (RCA), policy governance, human-in-the-loop approval, and controlled Kubernetes remediation.

---

## Current Release: v0.8.1 (Reliability & Test-Isolation Hardening)

**AgentOps-SRE v0.8.1** builds on the event-driven investigation platform of v0.8.0 by delivering **complete test-isolation hardening, formal test categorization, and worker lease reliability**:

- **🛡️ 100% Hermetic Unit Test Suite**: Decoupled unit tests from live Kubernetes clusters, Loki, Prometheus, and Ollama daemons using standardized in-memory test doubles (`MockSREMCPClient`). 173 unit tests pass in under 3.5 seconds with zero external dependencies.
- **🏷️ Pytest Marker Architecture**: Clean test categorization via `pytest -m unit`, `pytest -m integration`, and `pytest -m scenario` to prevent ambient cluster states from polluting fast unit verification loops.
- **💓 Adaptive Worker Heartbeat Lease Renewal**: Background heartbeat thread dynamically renews job leases at $\max(0.1, \min(40.0, \frac{\text{JOB\_LEASE\_SECONDS}}{3.0}))$, protecting long-running LLM investigations from false abandonment and split-brain execution.
- **⏱️ Inference Timeout & Fail-Closed Guard**: Verified `InferenceTimeoutError` handling fails closed cleanly with zero mock fallback or unauthorized remediation mutations.
- **⚙️ Multi-Tier CI Quality Workflows**: Fast, dependency-free pull request gate (`.github/workflows/ci.yml`) alongside a dedicated nightly disposable Kind cluster integration workflow (`.github/workflows/kind-integration.yml`).
- **📋 Documented Operational Limits**: Clear operational baselines for local Ollama latency profiles, disposable runner requirements, and replay benchmark scopes.

### Previous Milestone: v0.8.0 (Event-Driven Investigations & Operator Experience)

The platform supports:
- **🔄 Durable Asynchronous Investigation Engine**: SQLite WAL-mode transactional queue with dead worker lease recovery, stage progression tracking, and cooperative cancellation (`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `INCOMPLETE`, `CANCELLED`). `POST /api/incidents/investigate` returns `202 Accepted` immediately.
- **⚡ Live SSE Progress Streaming**: Server-Sent Events endpoint (`/api/investigations/<job_id>/stream`) with monotonic event IDs, keep-alive heartbeat comments (`: ping`), terminal `event: done`, and `Last-Event-ID` reconnection resumption.
- **📈 Grafana Dashboard Deep Integration**: Embedded dashboards via authenticated kiosk iframe or direct link (`GET /api/grafana/url`), origin validation, and query parameter isolation for Prometheus, Kubernetes, and Loki dashboards.
- **🚨 Prometheus Alertmanager Ingestion**: Webhook endpoint (`POST /api/v1/alerts`) with Alertmanager v4 payload schema validation, workload target validation, deduplication against `alert_deduplication` table, 300s alert storm cooldown, and optional shared secret authentication.
- **📧 SRE Operator Email Notifications**: SMTP delivery of investigation outcomes (`send_investigation_outcome_email`) with root cause summaries, confidence scores, and deep links to Web UI and Grafana dashboards.
- **🧩 Modular Vanilla Frontend Architecture**: ES modules (`api.js`, `investigation.js`, `dashboards.js`, `alerts.js`, `app.js`), 10-section operator console with tabs for Grafana Dashboards and Alertmanager Activity (zero npm or Node.js dependencies).
- **🔒 Autonomous Investigation, Controlled Remediation**: Webhooks and background workers can trigger investigations autonomously, but **never** authorize remediation. All remediation actions strictly require human approval through the policy engine and security gateway.

```text
       ┌───────────────────────────────┐        ┌───────────────────────────────┐
       │   Prometheus Alertmanager     │        │    SRE Operator Console /     │
       │   (Alert Evaluation Rules)    │        │       Direct API Request      │
       └──────────────┬────────────────┘        └──────────────┬────────────────┘
                      │ Webhook POST                           │ REST POST
                      ▼                                        ▼
       ┌────────────────────────────────────────────────────────────────────────┐
       │                 Alertmanager Receiver & Webhook API                    │
       │           (/api/v1/alerts - Payload Validation & Deduplication)        │
       └───────────────────────────────────┬────────────────────────────────────┘
                                           │ Enqueue Job
                                           ▼
       ┌────────────────────────────────────────────────────────────────────────┐
       │            Durable SQLite Job Store & Investigation Worker             │
       │         (WAL Mode, Lease Heartbeats, Cooperative Cancellation)         │
       └─────────────────┬──────────────────────────────────┬───────────────────┘
                         │ Progress Events                  │ Execute Investigation
                         ▼                                  ▼
       ┌───────────────────────────────────┐    ┌───────────────────────────────┐
       │   Server-Sent Events (SSE) Stream │    │           SRE Agent           │
       │   (/api/investigations/<id>/stream│    │ (Evidence Collection via MCP) │
       └─────────────────┬─────────────────┘    └──────────────┬────────────────┘
                         │                                     │
                         ▼                                     ▼
       ┌───────────────────────────────────┐    ┌───────────────────────────────┐
       │     Live Operator UI Progress     │    │      Real LLM Reasoning       │
       │  (Stages, Heartbeat, Cancel Btn)  │    │  (Ollama / OpenAI / Gemini)   │
       └───────────────────────────────────┘    └──────────────┬────────────────┘
                                                               │ ActionRequest
                                                               ▼
                                                ┌───────────────────────────────┐
                                                │         Policy Engine         │
                                                └──────────────┬────────────────┘
                                                               │ REQUIRE_APPROVAL
                                                               ▼
                                                ┌───────────────────────────────┐
                                                │    Approval Manager (HITL)    │
                                                │  (Single-Use Approval Token)  │
                                                └──────────────┬────────────────┘
                                                               │ APPROVED
                                                               ▼
                                                ┌───────────────────────────────┐
                                                │       Security Gateway        │
                                                │ (Re-validate, Mutation, Verify)
                                                └───────────────────────────────┘
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
# Start the web console & REST API server (starts in-process worker by default)
make ui
# or: make serve

# Optional: Run a dedicated standalone worker in another terminal
make worker
# or: uv run python -m agentops.cli worker
```
Open **`http://127.0.0.1:8000`** in your browser to access the 10-section operator console.

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

### Core & Observability
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

### Asynchronous Investigation Queue & SSE
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/incidents/investigate` | `POST` | Enqueue asynchronous investigation job (`202 Accepted` with `job_id`, or `sync=True` fallback) |
| `/api/investigations` | `GET` | List recent investigation jobs with state and trigger source |
| `/api/investigations/<job_id>` | `GET` | Retrieve investigation job details and current stage |
| `/api/investigations/<job_id>/events` | `GET` | Ordered diagnostic event history with `?after=<id>` pagination |
| `/api/investigations/<job_id>/stream` | `GET` | Server-Sent Events (SSE) live progress stream with monotonic IDs and keep-alive |
| `/api/investigations/<job_id>/result` | `GET` | Retrieve final `IncidentReport` (returns `409 Conflict` while running) |
| `/api/investigations/<job_id>/cancel` | `POST` | Safely cancel a queued or running investigation job |
| `/api/workers/status` | `GET` | Background worker queue depth, lease state, and active workers |

### Grafana & Alertmanager Integration
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/grafana/dashboards` | `GET` | List available Grafana dashboards and health check |
| `/api/grafana/url` | `GET` | Generate validated, sanitized kiosk-mode or direct dashboard URL |
| `/api/v1/alerts` | `POST` | Ingest Prometheus Alertmanager webhook notifications with deduplication |
| `/api/alerts/history` | `GET` | Retrieve history of ingested, deduplicated, and resolved alerts |

### Approvals, Chaos & Evaluation
| Endpoint | Method | Description |
| :--- | :--- | :--- |
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

> [!NOTE]
> **Replay Quality Gate vs. Live Diagnostic Accuracy**:
> The 96.5% benchmark score across the 6 evaluation scenarios measures **regression safety, deterministic pipeline integrity, and security invariant enforcement** against recorded operational fixtures. It is **not equivalent to 96.5% live LLM production diagnostic accuracy** on novel, unobserved incidents. Live diagnostic accuracy is governed by real-time cluster telemetry quality, prompt grounding, and the selected real model (e.g. Qwen, Granite, Gemini, OpenAI).

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
# Run hermetic unit tests (173 tests: schemas, security, policy, gateway, API, workflows, worker recovery, SSE streaming, Alertmanager, Grafana)
uv run pytest -m unit -v

# Run live infrastructure & MCP pipeline integration tests (requires live Kind cluster)
uv run pytest -m integration -v

# Run end-to-end incident investigation scenarios against live cluster
uv run pytest -m scenario -v

# Run regression evaluation benchmark gate (Replay mode)
uv run python -m agentops.cli eval gate --mode replay --provider mock

# Run all test suites
uv run pytest -v
```

---

## Known Operational Limits & Guidelines

1. **Local LLM Latency Profiles**: When using local inference (`ollama` with `qwen3.5:2b`), reasoning across complete multi-signal evidence typically takes **50–215 seconds** depending on host hardware. The worker lease heartbeat protects against false expiration, but `LLM_TIMEOUT_SECONDS` must remain set to at least `300` in local testing. Cloud providers (`openai` or `gemini`) are recommended for low-latency operational environments.
2. **Integration Test Environment**: The integration suite (`pytest -m integration`) and scenario suite (`pytest -m scenario`) require a running Kind cluster with NodePort mappings and the Prometheus/Loki/Alloy observability stack deployed. In CI/CD pipelines, this requires a Docker-enabled runner (e.g. GitHub Actions Ubuntu runner with `helm/kind-action`).
3. **Replay Benchmark Scope**: The 96.5% evaluation score verifies regression safety, tool adherence, and authorization boundaries across fixed scenario replays. It serves as a safety and consistency quality gate, not a guarantee of diagnostic accuracy on unseen, arbitrary production failure modes.

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
- [docs/architecture/v0.8-event-driven-investigations.md](docs/architecture/v0.8-event-driven-investigations.md): v0.8 Event-Driven Investigations & Operator Experience

---

## Teardown
```bash
make stop
```
