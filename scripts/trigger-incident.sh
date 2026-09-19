#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCENARIO="${1:-help}"

function show_usage() {
    echo -e "${BLUE}Usage:${NC} $0 <scenario>"
    echo ""
    echo "Available Scenarios:"
    echo -e "  ${YELLOW}crashloop${NC}            - Simulates fatal process crashes leading to CrashLoopBackOff"
    echo -e "  ${YELLOW}high-error-rate${NC}      - Simulates upstream 500 errors & degraded readiness"
    echo -e "  ${YELLOW}resource-exhaustion${NC}  - Simulates rapid memory leak leading to OOMKilled"
    echo -e "  ${YELLOW}bad-deployment${NC}       - Simulates broken deployment revision requiring rollback"
    echo -e "  ${GREEN}reset${NC}                - Restores demo-app to normal healthy state"
    echo ""
}

case "$SCENARIO" in
    crashloop)
        echo -e "${RED}======================================================${NC}"
        echo -e "${RED}   Triggering Incident: CrashLoopBackOff              ${NC}"
        echo -e "${RED}======================================================${NC}"
        echo -e "${BLUE}1. Patching demo-app with crashing entrypoint to cause CrashLoopBackOff...${NC}"
        kubectl patch deployment demo-app -n demo -p '{
          "spec": {
            "template": {
              "spec": {
                "containers": [{
                  "name": "demo-app",
                  "command": ["/bin/sh", "-c"],
                  "args": ["echo \"FATAL: Unhandled segmentation fault / panic triggered by threshold (1/1)\" && exit 1"]
                }]
              }
            }
          }
        }'

        echo -e "${BLUE}2. Waiting 15s for Kubernetes to restart the container and enter CrashLoopBackOff...${NC}"
        for i in {15..1}; do
            printf "\r   Entering CrashLoopBackOff: %2ds remaining..." "$i"
            sleep 1
        done
        echo -e "\n   ${GREEN}✓ CrashLoopBackOff triggered on Kubernetes!${NC}"

        echo -e "${YELLOW}3. Observable telemetry signals:${NC}"
        echo -e "   • ${CYAN}Kubernetes State:${NC} kubectl get pods -n demo -w"
        echo -e "   • ${CYAN}Kubernetes Events:${NC} kubectl get events -n demo --sort-by='.metadata.creationTimestamp'"
        echo -e "   • ${CYAN}PromQL Metric:${NC}     kube_pod_container_status_restarts_total"
        echo -e "   • ${CYAN}LogQL Query:${NC}       {namespace=\"demo\"} |= \"FATAL\""
        echo ""
        echo -e "Run ${GREEN}$0 reset${NC} to recover the deployment."
        ;;

    high-error-rate)
        echo -e "${RED}======================================================${NC}"
        echo -e "${RED}   Triggering Incident: High HTTP 500 Error Rate      ${NC}"
        echo -e "${RED}======================================================${NC}"
        echo -e "${BLUE}1. Patching demo-app with FAILURE_MODE=high_error_rate...${NC}"
        kubectl set env deployment/demo-app -n demo FAILURE_MODE=high_error_rate
        kubectl rollout restart deployment/demo-app -n demo
        kubectl rollout status deployment/demo-app -n demo --timeout=60s

        echo -e "${BLUE}2. Generating synthetic order traffic (20 requests to ensure Prometheus & Loki capture signals)...${NC}"
        for i in {1..20}; do
            STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:30080/orders \
                          -H "Content-Type: application/json" \
                          -d "{\"item\": \"order-batch-$i\", \"amount\": 1}" || echo "ERR")
            echo "   Order $i -> HTTP Status $STATUS"
            sleep 0.2
        done

        echo -e "${YELLOW}3. Waiting 30s for Prometheus scrape cycle and Loki log indexing...${NC}"
        for i in {30..1}; do
            printf "\r   Telemetry warm-up: %2ds remaining..." "$i"
            sleep 1
        done
        echo -e "\n   ${GREEN}✓ Telemetry ready for investigation!${NC}"

        echo -e "${YELLOW}4. Observable telemetry signals:${NC}"
        echo -e "   • ${CYAN}Readiness Probe:${NC}  curl -s http://localhost:30080/ready"
        echo -e "   • ${CYAN}PromQL Metric:${NC}    sum(rate(http_requests_total{status=\"500\"}[1m])) / sum(rate(http_requests_total[1m]))"
        echo -e "   • ${CYAN}LogQL Query:${NC}      {namespace=\"demo\"} | json | error_type=\"DatabaseConnectionTimeout\""
        echo ""
        echo -e "Run ${GREEN}$0 reset${NC} to recover the deployment."
        ;;

    resource-exhaustion)
        echo -e "${RED}======================================================${NC}"
        echo -e "${RED}   Triggering Incident: Memory Leak (OOMKilled)       ${NC}"
        echo -e "${RED}======================================================${NC}"
        echo -e "${BLUE}1. Patching demo-app with FAILURE_MODE=resource_exhaustion...${NC}"
        kubectl set env deployment/demo-app -n demo FAILURE_MODE=resource_exhaustion
        kubectl rollout restart deployment/demo-app -n demo
        kubectl rollout status deployment/demo-app -n demo --timeout=20s || true

        echo -e "${YELLOW}2. Memory allocation worker active. Pod will exceed 128Mi limit shortly.${NC}"
        echo -e "   • ${CYAN}Kubernetes State:${NC} kubectl get pods -n demo -w (watch for OOMKilled)"
        echo -e "   • ${CYAN}PromQL Metric:${NC}     app_memory_allocated_bytes"
        echo -e "   • ${CYAN}LogQL Query:${NC}       {namespace=\"demo\"} |= \"Memory allocation leak\""
        echo ""
        echo -e "Run ${GREEN}$0 reset${NC} to recover the deployment."
        ;;

    bad-deployment)
        echo -e "${RED}======================================================${NC}"
        echo -e "${RED}   Triggering Incident: Bad Deployment Revision       ${NC}"
        echo -e "${RED}======================================================${NC}"
        echo -e "${BLUE}1. Deploying broken image tag to demo-app...${NC}"
        kubectl set image deployment/demo-app demo-app=demo-app:broken-v2 -n demo
        echo -e "${YELLOW}2. Bad revision rolled out. New ReplicaSet will fail (ImagePullBackOff/ErrImagePull).${NC}"
        echo -e "   • ${CYAN}Kubernetes State:${NC} kubectl rollout status deployment/demo-app -n demo"
        echo -e "   • ${CYAN}Remediation:${NC}      Rollback to previous revision"
        echo ""
        echo -e "Run ${GREEN}$0 reset${NC} to recover the deployment."
        ;;

    reset)
        echo -e "${BLUE}======================================================${NC}"
        echo -e "${BLUE}   Resetting Demo Application to Healthy State        ${NC}"
        echo -e "${BLUE}======================================================${NC}"
        kubectl patch deployment demo-app -n demo --type json -p='[{"op": "remove", "path": "/spec/template/spec/containers/0/command"}, {"op": "remove", "path": "/spec/template/spec/containers/0/args"}]' 2>/dev/null || true
        kubectl apply -f kubernetes/demo-app/deployment.yaml
        kubectl rollout status deployment/demo-app -n demo --timeout=90s
        echo -e "${GREEN}✓ Demo application successfully restored to healthy state!${NC}"
        ;;

    *)
        show_usage
        exit 1
        ;;
esac
