.PHONY: all setup start stop status test test-infra demo clean preflight help

SHELL := /bin/bash
CLUSTER_NAME ?= agentops

all: help

help:
	@echo "AgentOps-SRE (v0.1) - Available Make Targets:"
	@echo "  make setup        - Run preflight, spin up cluster, deploy observability stack & demo app"
	@echo "  make start        - Start / ensure cluster and all workloads are running"
	@echo "  make stop         - Teardown Kind cluster"
	@echo "  make status       - Show status of cluster nodes, pods, and service URLs"
	@echo "  make test         - Run local Python unit tests"
	@echo "  make test-infra   - Run end-to-end infrastructure integration tests"
	@echo "  make demo         - Run interactive incident simulation walkthrough"
	@echo "  make preflight    - Verify local host environment dependencies"
	@echo "  make clean        - Remove virtualenv and temporary files"

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
	@uv run pytest tests/test_demo_app.py -v

test-infra:
	@uv run pytest tests/test_infrastructure.py -v

demo:
	@echo "================================================================"
	@echo "          AgentOps-SRE: Incident Reproduction Demo              "
	@echo "================================================================"
	@echo "1. Triggering High Error Rate incident..."
	@./scripts/trigger-incident.sh high-error-rate
	@sleep 4
	@echo ""
	@echo "2. Resetting to healthy state..."
	@./scripts/trigger-incident.sh reset
	@echo ""
	@echo "Demo finished. You can run individual incidents via:"
	@echo "  ./scripts/trigger-incident.sh crashloop"
	@echo "  ./scripts/trigger-incident.sh high-error-rate"
	@echo "  ./scripts/trigger-incident.sh resource-exhaustion"
	@echo "  ./scripts/trigger-incident.sh reset"

clean:
	@rm -rf .venv __pycache__ .pytest_cache
	@echo "Cleaned local virtual environment and caches."
