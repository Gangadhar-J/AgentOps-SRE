#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}       Deploying Observability Stack (monitoring)     ${NC}"
echo -e "${BLUE}======================================================${NC}"

# 1. Monitoring Namespace & Prometheus
echo -e "${BLUE}1. Deploying Prometheus (v3.14.0)...${NC}"
kubectl apply -f kubernetes/prometheus/namespace.yaml
kubectl apply -f kubernetes/prometheus/rbac.yaml
kubectl apply -f kubernetes/prometheus/configmap.yaml
kubectl apply -f kubernetes/prometheus/deployment.yaml
kubectl apply -f kubernetes/prometheus/service.yaml

# 2. Deploy Loki
echo -e "${BLUE}2. Deploying Loki (v3.7.6 - monolithic)...${NC}"
kubectl apply -f kubernetes/loki/configmap.yaml
kubectl apply -f kubernetes/loki/deployment.yaml
kubectl apply -f kubernetes/loki/service.yaml

# 3. Deploy Grafana Alloy
echo -e "${BLUE}3. Deploying Grafana Alloy (v1.19.2 - log collector)...${NC}"
kubectl apply -f kubernetes/alloy/rbac.yaml
kubectl apply -f kubernetes/alloy/configmap.yaml
kubectl apply -f kubernetes/alloy/daemonset.yaml

# 4. Deploy Grafana
echo -e "${BLUE}4. Deploying Grafana (v13.2.0)...${NC}"
kubectl apply -f kubernetes/grafana/datasources.yaml
kubectl apply -f kubernetes/grafana/deployment.yaml
kubectl apply -f kubernetes/grafana/service.yaml

# 5. Wait for readiness
echo -e "${BLUE}5. Waiting for monitoring stack components to be ready...${NC}"
kubectl rollout status deployment/prometheus -n monitoring --timeout=120s
kubectl rollout status deployment/loki -n monitoring --timeout=120s
kubectl rollout status deployment/grafana -n monitoring --timeout=120s
kubectl rollout status daemonset/alloy -n monitoring --timeout=120s

echo -e "${GREEN}✓ Observability stack is fully deployed and healthy!${NC}"
echo -e "  Prometheus UI: http://localhost:30090"
echo -e "  Grafana UI:    http://localhost:30300"
echo -e "  Loki API:      http://localhost:31000"
