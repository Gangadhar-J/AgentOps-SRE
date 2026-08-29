#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

CLUSTER_NAME="${CLUSTER_NAME:-agentops}"

echo -e "${BLUE}==> Ensuring Kind cluster '${CLUSTER_NAME}' is active...${NC}"

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo -e "${YELLOW}Cluster '${CLUSTER_NAME}' already exists. Switching context...${NC}"
    kubectl config use-context "kind-${CLUSTER_NAME}"
else
    echo -e "${BLUE}Creating Kind cluster '${CLUSTER_NAME}' with custom port mappings...${NC}"
    kind create cluster --config kubernetes/kind-config.yaml --name "${CLUSTER_NAME}"
fi

echo -e "${BLUE}Waiting for cluster node to become ready...${NC}"
kubectl wait --for=condition=Ready node --all --timeout=60s

echo -e "${GREEN}✓ Kind cluster '${CLUSTER_NAME}' is ready!${NC}"
