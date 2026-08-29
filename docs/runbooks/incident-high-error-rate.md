# Runbook: High HTTP 500 Error Rate Incident

## Incident Summary
The `demo-app` service encounters intermittent upstream failures (simulating database connection timeouts), returning HTTP 500 responses on ~50% of `/orders` requests and failing readiness checks.

## How to Trigger
```bash
./scripts/trigger-incident.sh high-error-rate
```

## Telemetry & Evidence Checklist

### 1. Kubernetes Readiness Probe
```bash
curl -i http://localhost:30080/ready
```
*Expected Signal:* HTTP 503 Service Unavailable with reason `High error rate detected in upstream database connection pool`.

### 2. Prometheus Metrics
Query PromQL in Prometheus UI (`http://localhost:30090`):
- **Error Rate Percentage**:
  ```promql
  sum(rate(http_requests_total{app="demo-app", status="500"}[1m])) 
  / 
  sum(rate(http_requests_total{app="demo-app"}[1m])) * 100
  ```
- **Failed Orders Counter**:
  ```promql
  app_orders_processed_total{status="failed"}
  ```

### 3. Loki Logs
Query LogQL in Grafana Explore (`http://localhost:30300`):
```logql
{namespace="demo", app="demo-app"} | json | status_code = 500
```
```logql
{namespace="demo", app="demo-app"} | json | error_type = "DatabaseConnectionTimeout"
```
*Expected Signal:* Stack traces and structured errors with `request_id` and `DatabaseConnectionTimeout`.

## Remediation / Recovery
```bash
./scripts/trigger-incident.sh reset
```
Verify recovery:
```bash
curl -s http://localhost:30080/ready
```
