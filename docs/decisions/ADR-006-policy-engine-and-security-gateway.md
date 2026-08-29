# ADR-006: Policy Engine and Authorizing Security Gateway

## Status
Accepted

## Context
In AI-driven operational architectures, allowing an LLM agent to directly execute infrastructure tools presents fundamental safety, security, and governance risks:
1. **Unbounded Agent Authority**: Without an authorization gateway, prompt injection or model hallucination can trigger catastrophic operational mutations (e.g. accidental database deletion, runaway scaling).
2. **Ambiguous Authorization**: LLMs cannot be trusted to evaluate whether their own actions conform to security policies.
3. **Lack of Default-Deny Governance**: Enterprise operations require a deterministic, declarative policy engine enforcing least-privilege access, constraint validation, and auditability.

## Decision
We established a deterministic **Policy Engine and Security Gateway** in Milestone v0.4.3:

```
     SRE Agent
         │
    ActionRequest  (Proposes action with target, reason, and evidence references)
         │
         ▼
  Security Gateway  (Intercepts every proposed action)
         │
         ▼
   Policy Engine   (Evaluates SecurityContext against declarative policies.yaml)
         │
         ├── DENY ───────────────► STOP (Execution blocked, audit record logged)
         ├── REQUIRE_APPROVAL ───► STOP (Human approval required, audit record logged)
         └── ALLOW ──────────────► MCP Client ──► MCP Server ──► Infrastructure
```

### 1. Default-Deny Policy Model
The Policy Engine strictly enforces **default-deny**. If no declarative policy explicitly authorizes the requested action, or if capabilities/constraints/evidence requirements are unsatisfied, the decision is `DENY`.

### 2. Precedence Hierarchy
Policy decisions follow strict deterministic precedence:
1. **Explicit DENY**: Critical global and targeted deny policies take absolute precedence over any allow rules.
2. **Capability / Constraint Failure**: Out-of-bounds namespaces, unpermitted resources, or replica limits result in `DENY`.
3. **Missing Evidence**: Policies requiring evidence fail with `DENY` if valid investigation evidence references are absent.
4. **REQUIRE_APPROVAL**: Remediation actions return `REQUIRE_APPROVAL` (halting autonomous execution).
5. **ALLOW**: Permitted read-only telemetry actions.

### 3. Risk Level is Policy-Governed
Risk classifications (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) are defined strictly within trusted policy configuration files (`config/policies.yaml`). The LLM cannot specify, modify, or downgrade risk.

### 4. Tamper-Resistant Audit Trail
Every evaluation generates an immutable `PolicyEvaluationRecord` recording the decision ID, agent ID, action, target, risk, decision outcome, matched policies, and violated constraints without storing secrets.

## Consequences
- **Zero Autonomous Mutations**: High-risk remediation actions are intercepted at the gateway with `REQUIRE_APPROVAL`.
- **Decoupled Governance**: Policy rules are maintained in human-readable YAML outside application code.
- **Fail-Safe Interception**: The Security Gateway prevents unapproved requests from ever reaching the MCP tool execution layer.
