.PHONY: all setup start stop status test test-infra test-scenarios test-api test-all eval eval-all eval-baseline eval-gate demo investigate incident ui serve clean preflight help

SHELL := /bin/bash
CLUSTER_NAME ?= agentops

all: help

help:
	@echo "AgentOps-SRE (v0.7) - Available Make Targets:"
	@echo "  make setup          - Run preflight, spin up cluster, deploy observability stack & demo app"
	@echo "  make start          - Start / ensure cluster and all workloads are running"
	@echo "  make stop           - Teardown Kind cluster"
	@echo "  make status         - Show status of cluster nodes, pods, and service URLs"
	@echo "  make ui             - Launch SRE Operator Console Web UI on http://127.0.0.1:8000"
	@echo "  make serve          - Run AgentOps Web UI & REST API server"
	@echo "  make incident       - Run single-command SRE incident investigation & recommendation"
	@echo "  make test           - Run local Python unit tests"
	@echo "  make test-api       - Run REST API & Operator workflow unit tests"
	@echo "  make test-infra     - Run end-to-end infrastructure & MCP pipeline integration tests"
	@echo "  make test-scenarios - Run full agent incident investigation scenarios against live cluster"
	@echo "  make test-all       - Run all test suites"
	@echo "  make eval           - Run default benchmark evaluation scenario"
	@echo "  make eval-all       - Run all benchmark scenarios (replay mode)"
	@echo "  make eval-baseline  - Save current benchmark results as baseline"
	@echo "  make eval-gate      - Run CI quality gate against baseline"
	@echo "  make investigate    - Run interactive CLI investigation for demo-app over MCP"
	@echo "  make demo           - Run incident reproduction demo"
	@echo "  make preflight      - Verify local host environment dependencies"
	@echo "  make clean          - Remove virtualenv and temporary caches"


preflight:
	@./scripts/preflight.sh

setup: preflight
	@./scripts/cluster-up.sh
	@./scripts/deploy-observability.sh
	@./scripts/deploy-demo-app.sh
	@$(MAKE) status

start:
	@./scripts/cluster-up.sh
	@$(MAKE) status

stop:
	@./scripts/cluster-down.sh

status:
	@echo ""
	@echo "================================================================"
	@echo "                   AgentOps-SRE Cluster Status                  "
	@echo "================================================================"
	@kubectl get nodes -o wide || true
	@echo ""
	@echo "--- Demo Namespace Pods ---"
	@kubectl get pods -n demo -o wide || true
	@echo ""
	@echo "--- Monitoring Namespace Pods ---"
	@kubectl get pods -n monitoring -o wide || true
	@echo ""
	@echo "================================================================"
	@echo "                   Service Access Endpoints                     "
	@echo "================================================================"
	@echo "  Demo Application: http://localhost:30080"
	@echo "  Prometheus UI:    http://localhost:30090"
	@echo "  Grafana UI:       http://localhost:30300 (Anonymous Admin)"
	@echo "  Loki API:         http://localhost:31000"
	@echo "================================================================"

test:
	@uv run pytest tests/test_demo_app.py tests/unit/ -v

test-api:
	@uv run pytest tests/unit/test_operator_api.py tests/unit/test_real_operator_console.py tests/unit/test_incident_workflow.py tests/unit/test_operator_cli.py -v

test-infra:
	@uv run pytest tests/test_infrastructure.py tests/integration/ -v

test-scenarios:
	@uv run pytest tests/scenario/ -v

test-all: test test-infra test-scenarios

eval:
	@uv run python -m agentops.cli eval run --scenario crashloop-001 --mode replay

eval-all:
	@uv run python -m agentops.cli eval run --all --mode replay --provider mock

eval-baseline:
	@uv run python -m agentops.cli eval baseline save --mode replay --provider mock --force

eval-gate:
	@uv run python -m agentops.cli eval gate --mode replay --provider mock

ui: serve

serve:
	@uv run python -m agentops.cli serve --host 127.0.0.1 --port 8000

incident:
	@uv run python -m agentops.cli incident demo/demo-app

investigate:
	@uv run python -m agentops.cli investigate --namespace demo --workload demo-app

demo:
	@echo "================================================================"
	@echo "          AgentOps-SRE: Incident Reproduction Demo (MCP)        "
	@echo "================================================================"
	@echo "1. Triggering High Error Rate incident..."
	@./scripts/trigger-incident.sh high-error-rate
	@sleep 4
	@echo ""
	@echo "2. Running AI SRE Investigation Agent over MCP..."
	@$(MAKE) investigate
	@sleep 2
	@echo ""
	@echo "3. Resetting to healthy state..."
	@./scripts/trigger-incident.sh reset
	@echo ""
	@echo "Demo finished."

clean:
	@rm -rf .venv __pycache__ .pytest_cache tests/**/__pycache__
	@echo "Cleaned local virtual environment and caches."
