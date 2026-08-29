.PHONY: all setup start stop status test test-infra test-scenarios test-all demo investigate clean preflight help

SHELL := /bin/bash
CLUSTER_NAME ?= agentops

all: help

help:
	@echo "AgentOps-SRE (v0.2) - Available Make Targets:"
	@echo "  make setup          - Run preflight, spin up cluster, deploy observability stack & demo app"
	@echo "  make start          - Start / ensure cluster and all workloads are running"
	@echo "  make stop           - Teardown Kind cluster"
	@echo "  make status         - Show status of cluster nodes, pods, and service URLs"
	@echo "  make test           - Run local Python unit tests (clients, models, security guards)"
	@echo "  make test-infra     - Run end-to-end infrastructure integration tests"
	@echo "  make test-scenarios - Run full agent incident investigation scenarios against live cluster"
	@echo "  make test-all       - Run all test suites"
	@echo "  make investigate    - Run interactive CLI investigation for demo-app"
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

test-infra:
	@uv run pytest tests/test_infrastructure.py -v

test-scenarios:
	@uv run pytest tests/scenario/ -v

test-all: test test-infra test-scenarios

investigate:
	@uv run python -m agentops.cli investigate --namespace demo --workload demo-app

demo:
	@echo "================================================================"
	@echo "          AgentOps-SRE: Incident Reproduction Demo              "
	@echo "================================================================"
	@echo "1. Triggering High Error Rate incident..."
	@./scripts/trigger-incident.sh high-error-rate
	@sleep 4
	@echo ""
	@echo "2. Running AI SRE Investigation Agent..."
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
