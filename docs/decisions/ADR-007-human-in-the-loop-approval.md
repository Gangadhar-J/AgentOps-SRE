# ADR-007: Human-in-the-Loop Approval Workflow and Replay Protection

## Status
Accepted

## Context
In Milestone v0.4.3, we introduced the Policy Engine and Security Gateway, establishing `REQUIRE_APPROVAL` as the mandatory authorization outcome for remediation actions. However, without a dedicated approval management layer:
1. **Unstructured Approval Handling**: Systems may resort to ad-hoc, untracked approval flags that can be forged by the agent.
2. **Replay Vulnerabilities**: An approved remediation request could be captured and replayed indefinitely to execute unauthorized operations.
3. **Stale Approvals & Drift**: An approval granted hours or days prior might no longer reflect the current cluster state or updated security policies.
4. **Lack of Operator Attribution**: Actions must be explicitly attributed to authenticated human operators without storing secrets or passwords.

## Decision
We established a deterministic **Human-in-the-Loop Approval Workflow** in Milestone v0.4.4:

```
     SRE Agent
         │
    ActionRequest  (Proposed action with target, reason, evidence refs)
         │
         ▼
  Security Gateway  (Evaluates PolicyEngine -> REQUIRE_APPROVAL)
         │
         ▼
  ApprovalManager   (Creates ApprovalRequest in PENDING state with TTL)
         │
         ▼
  Human Operator    (Reviews ActionRequest + Evidence, decides APPROVE/REJECT)
         │
         ▼
  Security Gateway  (Re-validates binding, policy, expiry, and single-use consumption)
         │
         ▼
  Safe Execution    (Mock execution callback / Future MCP write tool)
```

### 1. Strict State Machine
Approval requests transition strictly through:
- `PENDING` -> `APPROVED`
- `PENDING` -> `REJECTED`
- `PENDING` -> `EXPIRED`
- `APPROVED` -> `CONSUMED` (single-use execution)
All backwards or invalid transitions are strictly prohibited.

### 2. Request Binding & Tamper Resistance
Every `ApprovalRequest` binds immutably to the original `ActionRequest` (action, target, reason, evidence references) and `PolicyDecision`. If an agent submits a modified target or altered evidence references under an existing approval ID, the gateway rejects execution with `DENY`.

### 3. Re-Validation at Gateway Execution
Approval state alone does not guarantee execution. When execution is requested, the Security Gateway re-evaluates:
1. Approval status is `APPROVED` and has not expired.
2. The `ActionRequest` exactly matches the approval binding.
3. The live `PolicyEngine` still authorizes the request (protecting against policy revocations).
4. The approval is immediately marked `CONSUMED` before executing the callback (single-use replay protection).

### 4. Persistent Storage (SQLite)
Approvals and audit transitions are stored durably in `data/agentops.db`, ensuring that approval state and audit records survive process restarts.

## Consequences
- **Zero Autonomous Execution**: High-risk remediation cannot execute without explicit human authorization.
- **Single-Use Replay Protection**: Consumed approvals cannot be re-executed.
- **Durable Audit Trail**: Operator identity, decision justification, and timestamps are recorded in `approval_records`.
- **Prepares for v0.5**: Provides the exact authorization interface needed before introducing controlled Kubernetes write tools.
