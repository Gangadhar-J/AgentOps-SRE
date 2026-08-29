#!/usr/bin/env bash
set -euo pipefail

# ANSI Color Codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}       AgentOps-SRE: Pre-flight Environment Checks    ${NC}"
echo -e "${BLUE}======================================================${NC}"

ERRORS=0

# 1. Check Docker binary and daemon
if command -v docker >/dev/null 2>&1; then
    echo -e " [${GREEN}OK${NC}] Docker CLI found: $(docker --version)"
    if docker info >/dev/null 2>&1; then
        echo -e " [${GREEN}OK${NC}] Docker daemon is running and reachable"
    else
        echo -e " [${RED}FAIL${NC}] Docker daemon is NOT running. Please start Docker Desktop."
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e " [${RED}FAIL${NC}] Docker is not installed or not in PATH."
    ERRORS=$((ERRORS + 1))
fi

# 2. Check Kind
if command -v kind >/dev/null 2>&1; then
    echo -e " [${GREEN}OK${NC}] Kind found: $(kind version)"
else
    echo -e " [${RED}FAIL${NC}] Kind is not installed. Install via: brew install kind"
    ERRORS=$((ERRORS + 1))
fi

# 3. Check kubectl
if command -v kubectl >/dev/null 2>&1; then
    echo -e " [${GREEN}OK${NC}] kubectl found: $(kubectl version --client -o json 2>/dev/null | grep gitVersion || kubectl version --client 2>&1 | head -n 1)"
else
    echo -e " [${RED}FAIL${NC}] kubectl is not installed. Install via: brew install kubectl"
    ERRORS=$((ERRORS + 1))
fi

# 4. Check uv / Python
if command -v uv >/dev/null 2>&1; then
    echo -e " [${GREEN}OK${NC}] uv found: $(uv --version)"
else
    echo -e " [${YELLOW}WARN${NC}] uv is not installed. Using standard python3/pip as fallback."
fi

if command -v python3 >/dev/null 2>&1; then
    echo -e " [${GREEN}OK${NC}] python3 found: $(python3 --version)"
else
    echo -e " [${RED}FAIL${NC}] python3 is not installed."
    ERRORS=$((ERRORS + 1))
fi

echo -e "${BLUE}------------------------------------------------------${NC}"
if [ "$ERRORS" -gt 0 ]; then
    echo -e "${RED}Pre-flight checks failed with ${ERRORS} error(s). Please resolve before proceeding.${NC}"
    exit 1
else
    echo -e "${GREEN}All pre-flight checks passed! Local environment is ready.${NC}"
    exit 0
fi
