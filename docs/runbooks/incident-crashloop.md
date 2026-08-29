# Runbook: CrashLoopBackOff Incident

## Incident Summary
The `demo-app` service experiences fatal process crashes upon processing requests, exceeding Kubernetes restart backoff thresholds and entering a `CrashLoopBackOff` state.

## How to Trigger
```bash
./scripts/trigger-incident.sh crashloop
```

## Telemetry & Evidence Checklist

### 1. Kubernetes State
Check pod lifecycle status and restarts:
```bash
kubectl get pods -n demo -l app=demo-app
```
*Expected Signal:* Pod status shows `CrashLoopBackOff` or `Error`, with `RESTARTS` count > 1.

Check container termination reason and exit code:
```bash
kubectl get pods -n demo -l app=demo-app -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\tExitCode:"}{.status.containerStatuses[*].lastState.terminated.exitCode}{"\n"}{end}'
```
*Expected Signal:* `Error`, `ExitCode: 1`.

Check Kubernetes Events:
```bash
kubectl get events -n demo --field-selector reason=BackOff --sort-by='.metadata.creationTimestamp'
```
*Expected Signal:* Warning events with reason `BackOff` ("Back-off restarting failed container").

### 2. Prometheus Metrics
Query PromQL in Prometheus UI (`http://localhost:30090`):
- **Pod Restarts**: `changes(kube_pod_container_status_restarts_total[5m])` or `increase(http_requests_total[2m])`

### 3. Loki Logs
Query LogQL in Grafana Explore (`http://localhost:30300`):
```logql
{namespace="demo", app="demo-app"} |= "FATAL"
```
```logql
{namespace="demo", app="demo-app"} | json | error_type="FatalProcessCrash"
```
*Expected Signal:* JSON log containing fatal crash notice and Python stack trace before exit.

## Remediation / Recovery
```bash
./scripts/trigger-incident.sh reset
```
Verify recovery:
```bash
kubectl get pods -n demo -l app=demo-app
curl -s http://localhost:30080/health
```
