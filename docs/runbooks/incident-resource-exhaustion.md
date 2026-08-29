# Runbook: Resource Exhaustion (OOMKilled) Incident

## Incident Summary
A background worker leaks memory rapidly by allocating bytearrays without releasing them. When working set memory exceeds the container's 128Mi limit, the Linux cgroups OOM killer terminates the container with signal 137 (`OOMKilled`).

## How to Trigger
```bash
./scripts/trigger-incident.sh resource-exhaustion
```

## Telemetry & Evidence Checklist

### 1. Kubernetes State
Watch pods get terminated:
```bash
kubectl get pods -n demo -w
```
Inspect last termination state:
```bash
kubectl get pods -n demo -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\tExitCode:"}{.status.containerStatuses[*].lastState.terminated.exitCode}{"\n"}{end}'
```
*Expected Signal:* `OOMKilled`, `ExitCode: 137`.

Check Kubernetes Events:
```bash
kubectl get events -n demo --field-selector reason=OOMKilled
```

### 2. Prometheus Metrics
Query PromQL in Prometheus UI (`http://localhost:30090`):
- **Synthetic Memory Allocation**:
  ```promql
  app_memory_allocated_bytes{app="demo-app"}
  ```

### 3. Loki Logs
Query LogQL in Grafana Explore (`http://localhost:30300`):
```logql
{namespace="demo", app="demo-app"} |= "Memory allocation leak"
```
*Expected Signal:* Warning logs showing memory allocation escalating in chunks.

## Remediation / Recovery
```bash
./scripts/trigger-incident.sh reset
```
