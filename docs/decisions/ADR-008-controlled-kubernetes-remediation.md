# ADR-008: Controlled Kubernetes Remediation and Post-Execution Verification

## Status
Accepted

## Context
Autonomous operational agents without bounded, verifiable mutation capabilities pose extreme availability and security hazards:
1. **Unbounded Mutation Blast Radius**: Providing an LLM with generic `kubectl` or `patch`/`delete` endpoints allows accidental or malicious deletion of namespaces, secrets, or databases.
2. **Execution Without Evidence or Approval**: Remediations executed without binding to concrete investigation evidence bypass human oversight and change management audit requirements.
3. **Premature Success Declarations**: Marking remediation successful solely because an API call returned HTTP 200 ignores underlying workload states (e.g. failing readiness probes or continued crash loops).

## Decision
We established a strict **Controlled Kubernetes Remediation Architecture** in Milestone v0.5:

```
Incident ──► Evidence & RCA ──► ActionRequest ──► PolicyEngine ──► REQUIRE_APPROVAL
                                                                        │
                                                                 Human Approval
                                                                        │
                                                                     APPROVED
                                                                        │
                                                                 Security Gateway
                                                               (Re-validation & Bind)
                                                                        │
                                                            MCP Write Tool (3 only)
                                                                        │
                                                                 Kubernetes API
                                                                        │
                                                            Post-Action Verification
                                                          (Readiness, Rollout, Pods)
```

### 1. Exactly Three Controlled Operations
The MCP Server and `KubernetesRemediationClient` expose exclusively:
1. `k8s.remediation.restart_deployment`: Native rolling restart via timestamp patch.
2. `k8s.remediation.scale_deployment`: Replicas adjustment within strict safe bounds (`[1, 10]`).
3. `k8s.remediation.rollback_deployment`: Rollout undo to a specific or previous revision.
Generic mutations (`delete`, `exec`, `apply`, `raw_patch`) are strictly prohibited and absent.

### 2. Pre-Remediation Snapshot
Before applying any cluster mutation, a `PreRemediationSnapshot` is captured (recording replicas, pod count, container states, image, and restart counts) for audit and rollback comparison.

### 3. Post-Remediation Verification
Execution is only declared `SUCCESS` if post-action verification proves:
- Deployment rollout has fully completed.
- Pods have transitioned to `Ready: True`.
- Replica counts match desired values without unexpected crash loops.

### 4. Single-Use Replay Protection & Re-validation
Remediation executions require an approved `ApprovalRequest`. The Security Gateway re-evaluates policy rules, verifies exact request binding, and marks the approval as `CONSUMED` before calling Kubernetes.

## Consequences
- **Narrow Blast Radius**: Remediation is strictly restricted to deployment lifecycle actions.
- **Fail-Safe Operation**: If verification times out or fails, `RemediationResult.status` is marked `FAILED` without automatic retry loops.
- **Durable Audit Trail**: Captures why the action was requested, who approved it, what changed, and before/after verification telemetry.
