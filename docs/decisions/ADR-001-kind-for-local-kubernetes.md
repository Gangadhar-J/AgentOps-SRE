# ADR-001: Kind for Local Kubernetes Cluster

## Status
Accepted

## Context
AgentOps-SRE is a local-first platform designed to run completely on developer workstations (macOS Apple Silicon). We required a local Kubernetes runtime that:
1. Supports native multi-architecture (`darwin/arm64`) Docker containers.
2. Supports declarative cluster configuration including host port mappings for NodePort services.
3. Is lightweight, fast to create and destroy, and requires zero external cloud dependencies.
4. Conforms to standard Kubernetes API specifications.

## Decision
We selected **Kind (Kubernetes in Docker)** as the local cluster engine.

## Alternatives Considered
- **Minikube**: Heavier virtualization layer; driver configuration can be brittle across macOS updates.
- **k3d / K3s**: Fast and lightweight, but introduces K3s-specific API variances compared to standard upstream Kubernetes.
- **Docker Desktop Kubernetes**: Single static instance; lacks declarative multi-cluster automation via code/Makefiles.

## Consequences
- Single-node Kind cluster can be spun up in <30 seconds via `make setup`.
- Container port mappings allow direct localhost access to Prometheus (`:30090`), Grafana (`:30300`), Demo App (`:30080`), and Loki (`:31000`) without fragile `kubectl port-forward` background processes.
