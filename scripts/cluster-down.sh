#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

CLUSTER_NAME="${CLUSTER_NAME:-agentops}"

echo -e "${BLUE}==> Deleting Kind cluster '${CLUSTER_NAME}'...${NC}"
kind delete cluster --name "${CLUSTER_NAME}"
echo -e "${GREEN}✓ Kind cluster '${CLUSTER_NAME}' deleted successfully.${NC}"
