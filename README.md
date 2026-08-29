# AgentOps-SRE

> Production-style, local-first **AI SRE / AgentOps Platform** demonstrating safe, evidence-backed incident investigation, root-cause analysis (RCA), and policy-governed remediation on Kubernetes.

---

## Current Status: Milestone v0.1 (Infrastructure & Observability Foundation)

Milestone **v0.1** establishes the reproducible Kubernetes infrastructure, failure-prone demo microservice, and local observability stack. It generates multi-modal telemetry (metrics, structured logs, Kubernetes state & events) that the future AI SRE agent (v0.2+) will reason over.

```
┌─────────────────────────────────────────────────────────────┐
│                    Kind Cluster (agentops)                   │
│                                                             │
│  ┌─────────────────────────┐  ┌──────────────────────────┐  │
│  │     demo namespace      │  │   monitoring namespace   │  │
│  │                         │  │                          │  │
│  │  ┌───────────────────┐  │  │  ┌────────────────────┐  │  │
│  │  │  demo-app         │  │  │  │  Prometheus        │  │  │
│  │  │  (Flask/Gunicorn) │──│──│──│  v3.14.0           │  │  │
│  │  │  /metrics ────────│──│──│──│  :30090            │  │  │
│  │  │  :30080           │  │  │  └────────────────────┘  │  │
│  │  └───────────────────┘  │  │                          │  │
│  └─────────────────────────┘  │  ┌────────────────────┐  │  │
│                               │  │  Loki              │  │  │
│  ┌─────────────────────────┐  │  │  v3.7.6 (Monolith) │  │  │
│  │  DaemonSet (All Nodes)  │  │  │  :31000            │  │  │
│  │                         │  │  └─────────▲──────────┘  │  │
│  │  ┌───────────────────┐  │  │            │             │  │
│  │  │  Grafana Alloy    │──│──│────────────┘             │  │
│  │  │  v1.19.2          │  │  │                          │  │
│  │  │  (Log Collector)  │  │  │  ┌────────────────────┐  │  │
│  │  └───────────────────┘  │  │  │  Grafana           │  │  │
│  └─────────────────────────┘  │  │  v13.2.0           │  │  │
│                               │  │  :30300            │  │  │
│                               │  └────────────────────┘  │  │
│                               └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Service Endpoints

Once started, all services are accessible on host ports without needing manual port-forwarding:

| Service | Host URL | Description |
|---------|----------|-------------|
| **Demo Application** | [http://localhost:30080](http://localhost:30080) | Order processing service (`/orders`, `/health`, `/metrics`) |
| **Prometheus UI** | [http://localhost:30090](http://localhost:30090) | Time-series metrics engine & PromQL console |
| **Grafana UI** | [http://localhost:30300](http://localhost:30300) | Visualization dashboards (pre-provisioned Prometheus & Loki) |
| **Loki API** | [http://localhost:31000](http://localhost:31000) | Monolithic log aggregation engine |

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
# Run unit tests (demo application logic & JSON log formatting)
make test

# Run infrastructure integration tests against the live cluster
make test-infra
```

---

## Reproducible Incident Scenarios

The demo application features built-in failure simulation modes to generate realistic incident telemetry:

### 1. CrashLoopBackOff
Simulates unhandled panic / segmentation faults:
```bash
./scripts/trigger-incident.sh crashloop
```
- **Observed signals**: Pod exit code 1, `CrashLoopBackOff` state, fatal stack trace in Loki, restart counter metric increase.
- **Runbook**: [docs/runbooks/incident-crashloop.md](docs/runbooks/incident-crashloop.md)

### 2. High HTTP 500 Error Rate
Simulates database connection timeout failures:
```bash
./scripts/trigger-incident.sh high-error-rate
```
- **Observed signals**: HTTP 500 spikes in `http_requests_total`, readiness probe failures (`/ready` returns 503), error logs with stack traces.
- **Runbook**: [docs/runbooks/incident-high-error-rate.md](docs/runbooks/incident-high-error-rate.md)

### 3. Resource Exhaustion (OOMKilled)
Simulates progressive memory leaks:
```bash
./scripts/trigger-incident.sh resource-exhaustion
```
- **Observed signals**: Memory allocation logs, cgroups memory limit breached, pod terminated with signal 137 (`OOMKilled`).
- **Runbook**: [docs/runbooks/incident-resource-exhaustion.md](docs/runbooks/incident-resource-exhaustion.md)

### 4. Incident Recovery / Reset
Restore the application to normal healthy state:
```bash
./scripts/trigger-incident.sh reset
```

---

## Teardown
```bash
make stop
```

---

## Repository Structure

```
AgentOps-SRE/
├── Makefile                          # Developer command entry point
├── README.md                         # Project documentation
├── pyproject.toml                    # Python project & dev dependencies
├── .env.example                      # Configurable cluster & port variables
│
├── demo-app/                         # Failure-prone order service
│   ├── app.py                        # Flask API + Prometheus metrics + JSON logs
│   ├── Dockerfile                    # Container definition (Python 3.12-slim)
│   └── requirements.txt              # Runtime dependencies
│
├── kubernetes/                       # Declarative K8s manifests
│   ├── kind-config.yaml              # Kind cluster with NodePort mappings
│   ├── demo-app/                     # Demo app Deployment, Service, Namespace
│   ├── prometheus/                   # Prometheus Deployment, ConfigMap, RBAC, Service
│   ├── loki/                         # Loki Monolithic Deployment, ConfigMap, Service
│   ├── alloy/                        # Grafana Alloy DaemonSet, ConfigMap, RBAC
│   └── grafana/                      # Grafana Deployment, Datasource provisioning
│
├── scripts/                          # Lifecycle & incident automation
│   ├── preflight.sh                  # Host dependency check
│   ├── cluster-up.sh                 # Kind cluster provisioning
│   ├── cluster-down.sh               # Kind cluster destruction
│   ├── deploy-observability.sh       # Deploy Prometheus, Loki, Alloy, Grafana
│   ├── deploy-demo-app.sh            # Build & deploy demo application
│   └── trigger-incident.sh           # Incident trigger and reset script
│
├── tests/                            # Automated test suite
│   ├── test_demo_app.py              # Unit tests for application logic
│   └── test_infrastructure.py        # Integration tests for K8s & observability
│
└── docs/                             # Architecture docs & runbooks
    ├── architecture/
    │   └── v0.1-overview.md          # Architecture overview & correlation model
    ├── decisions/
    │   ├── ADR-001-kind-for-local-kubernetes.md
    │   └── ADR-002-alloy-over-promtail.md
    └── runbooks/
        ├── incident-crashloop.md
        ├── incident-high-error-rate.md
        └── incident-resource-exhaustion.md
```
