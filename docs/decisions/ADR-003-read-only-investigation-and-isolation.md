# ADR-003: Read-Only Investigation Boundary and LLM Isolation

## Status
Accepted

## Context
In an autonomous or AI-assisted infrastructure management platform, allowing a Large Language Model (LLM) to directly construct or execute shell commands (e.g. `kubectl delete`, `kubectl patch`, `kubectl exec`) introduces severe security, reliability, and stability risks:
1. **Prompt Injection & Jailbreaks**: An attacker who can influence telemetry (e.g. via crafted request headers or log entries) could manipulate the LLM into generating destructive infrastructure commands.
2. **Hallucinated Syntax & Side-Effects**: LLMs are non-deterministic; generating raw CLI commands risks unintentional infrastructure destruction or cascading cluster outages.
3. **Privilege Escalation**: Direct API/cluster access bypasses principle of least privilege.
4. **Lack of Auditability**: Dynamic shell commands are difficult to parse, policy-check, and audit reliably before execution.

## Decision
We established a strict **Read-Only Investigation Boundary** in v0.2:
1. **The LLM Never Accesses Kubernetes Directly**: The LLM interacts only with normalized, structured `InvestigationContext` representations provided by the `InvestigationOrchestrator`.
2. **Code-Enforced Read-Only Kubernetes Client**: The `KubernetesInvestigationClient` exclusively implements `get_*` and `list_*` inspection methods. Prohibited mutations (`delete`, `patch`, `scale`, `exec`, `restart`) do not exist in the client interface and are explicitly guarded against.
3. **Deterministic Telemetry Normalization**: Telemetry from Prometheus, Loki, and Kubernetes is gathered, parsed, and assigned stable evidence IDs (`E001`, `E002`...) outside the LLM.
4. **Human-in-the-Loop Remediations**: The RCA output schema enforces `requires_human_approval = True`. The agent can *propose* remediation steps in structured text, but has zero mechanism to execute them.

## Consequences
- **Security**: The system is resilient to prompt injection aiming to execute unauthorized cluster modifications because the execution path literally does not exist in code.
- **Auditability**: Every root cause diagnosis references discrete, immutable evidence IDs directly tied to raw telemetry extracts.
- **Extensibility**: In v0.3, the structured tool interfaces (`KubernetesInvestigationTools`, `PrometheusInvestigationTools`, `LokiInvestigationTools`) can be wrapped directly as Model Context Protocol (MCP) tools without refactoring the investigation logic.
