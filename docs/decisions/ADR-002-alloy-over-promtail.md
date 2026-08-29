# ADR-002: Grafana Alloy as Successor to Promtail for Log Collection

## Status
Accepted

## Context
Promtail was historically the standard log collector for Grafana Loki. However, in **March 2026, Promtail reached End-of-Life (EOL)** and is no longer maintained or supported by Grafana Labs.

## Decision
We chose **Grafana Alloy** (`grafana/alloy:v1.19.2`) as the log collection DaemonSet rather than Promtail.

## Trade-offs
- **Pros**:
  - Actively maintained and officially recommended for all new Loki deployments.
  - Native multi-architecture support on Apple Silicon (`linux/arm64`).
  - Unified OpenTelemetry-compatible architecture supporting logs, metrics, and traces.
  - Declarative configuration syntax (River/HCL) with built-in Kubernetes discovery (`loki.source.kubernetes`).
- **Cons**:
  - Slightly higher memory footprint (~100-150MB) compared to legacy Promtail (~50MB), which is well within acceptable limits for developer workstations.

## Consequences
- The cluster runs modern, production-grade log collection aligned with current industry standards.
