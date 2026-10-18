#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

CLUSTER_NAME="${CLUSTER_NAME:-agentops}"

echo -e "${BLUE}==> Stopping any running AgentOps web server (port 8000)...${NC}"
lsof -ti :8000 | xargs kill -9 2>/dev/null || true

echo -e "${BLUE}==> Deleting Kind cluster '${CLUSTER_NAME}'...${NC}"
kind delete cluster --name "${CLUSTER_NAME}"
echo -e "${GREEN}✓ Kind cluster '${CLUSTER_NAME}' and AgentOps services stopped successfully.${NC}"
