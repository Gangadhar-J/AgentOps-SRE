# ADR-005: Agent Identity and Capability-Based Security Model

## Status
Accepted

## Context
In autonomous and AI-assisted operational systems, allowing an AI agent to execute infrastructure actions or construct arbitrary tool calls without verifiable identity and authority bounds introduces grave operational and security risks:
1. **Agent Impersonation & Ambient Authority**: If agents operate without explicit, immutable identities, audits cannot attribute actions to specific agent instances, versions, or owners.
2. **Confused Deputy & Authority Hijacking**: If the permissions granted to an agent are entangled with its natural-language requests, prompt injection could induce the agent to declare its own permissions.
3. **Broad / Wildcard Escalation**: Coarse-grained permissions (e.g. `k8s.*` or `admin`) violate the principle of least privilege and allow runaway remediation failures to impact unrelated workloads.
4. **Unsubstantiated Actions**: If remediation actions are proposed without tying them directly to immutable investigation evidence, human operators and policy engines cannot verify *why* an action was proposed.

## Decision
We established a strict, decoupled **Identity and Capability Model** in Milestone v0.4.1 & v0.4.2:

```
     Agent Identity                Capabilities                ActionRequest
   (Who is the agent?)      (What authority is granted?)  (What is proposed & why?)
            │                            │                            │
            └────────────────────────────┼────────────────────────────┘
                                         │
                                         ▼
                                  SecurityContext
                    (Identity + Granted Capabilities + Request ID)
                                         │
                                         ▼
                                Future Policy Engine
                            (Is this action permitted?)
```

### 1. Separation of Identity from Capabilities
`AgentIdentity` answers *"Who is this agent?"* (e.g. instance ID, version, agent type), while `Capability` answers *"What authority has been granted to this identity by the platform administrator?"*. Keeping these separate ensures permissions are administered out-of-band and never declared by the agent itself.

### 2. Separation of Capabilities from ActionRequests
A `Capability` represents granted authority (e.g. permission to restart deployments in namespace `demo`). An `ActionRequest` represents an intent to act (e.g. "restart deployment `demo-app` because of CrashLoopBackOff with evidence `E001`"). Authority is passive; requests are active.

### 3. The LLM Cannot Define Its Own Identity
The `AgentIdentity` is constructed strictly by the trusted runtime environment (configuration / orchestration layer) with immutability enforced (`frozen=True`) and secret-scanning guards. The LLM has zero capability to generate, modify, or spoof its identity.

### 4. Prohibition of Wildcards
Capability names must follow the strict taxonomy `<domain>.<operation>.<resource>` (e.g. `k8s.read.pods`, `k8s.remediation.restart_deployment`). Wildcards (`*`, `k8s.*`, `k8s.admin`, `all`) are strictly rejected at the schema level to enforce least-privilege scoping.

### 5. Evidence References in ActionRequests
Every `ActionRequest` must cite one or more valid investigation evidence references (`evidence_refs: ["E001", "E004"]`). This ensures that actions are not arbitrary or hallucinated, providing an unbroken audit trail from telemetry to remediation.

### 6. Authorization Deferred to Policy Engine
Neither `Capability` nor `ActionRequest` contains authorization decision fields (e.g. `approved=True`). Authorization is deliberately deferred to the **Security / Policy Gateway** (Milestone v0.4.3+), ensuring clean separation between security primitives and policy evaluation rules.

## Consequences
- **Least Privilege**: Platform engineers can grant fine-grained, scoped capabilities (e.g. read pods only in `demo` namespace).
- **Tamper Resistance**: Pydantic immutability prevents in-memory tampering of identities and capabilities.
- **Audit Readiness**: Every action request contains structured targets, reasons, and evidence IDs suitable for immutable audit logging.
- **Foundational for v0.4.3**: Provides clean, typed security primitives ready to be consumed by the future policy engine and security gateway.
