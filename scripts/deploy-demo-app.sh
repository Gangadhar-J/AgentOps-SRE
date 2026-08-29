#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

CLUSTER_NAME="${CLUSTER_NAME:-agentops}"

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}       Building & Deploying Demo Application          ${NC}"
echo -e "${BLUE}======================================================${NC}"

# 1. Build Docker image
echo -e "${BLUE}1. Building demo-app:v0.1 Docker image...${NC}"
docker build -t demo-app:v0.1 demo-app/

# 2. Load into Kind cluster
echo -e "${BLUE}2. Loading demo-app:v0.1 into Kind cluster '${CLUSTER_NAME}'...${NC}"
kind load docker-image demo-app:v0.1 --name "${CLUSTER_NAME}"

# 3. Apply manifests
echo -e "${BLUE}3. Applying demo-app Kubernetes manifests...${NC}"
kubectl apply -f kubernetes/demo-app/namespace.yaml
kubectl apply -f kubernetes/demo-app/deployment.yaml
kubectl apply -f kubernetes/demo-app/service.yaml

# 4. Wait for deployment
echo -e "${BLUE}4. Waiting for demo-app rollout...${NC}"
kubectl rollout status deployment/demo-app -n demo --timeout=120s

echo -e "${GREEN}✓ Demo application is successfully deployed and running!${NC}"
echo -e "  Demo App URL: http://localhost:30080"
echo -e "  Health Check: http://localhost:30080/health"
echo -e "  Metrics:      http://localhost:30080/metrics"
