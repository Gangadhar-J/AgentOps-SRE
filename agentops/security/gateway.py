from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple
import uuid
from agentops.clients.remediation import KubernetesRemediationClient
from agentops.models.remediation import (
    PreRemediationSnapshot,
    RemediationMetricsTracker,
    RemediationResult,
    RemediationVerification,
)
from agentops.security.approval import ApprovalManager, ApprovalRequest
from agentops.security.audit import AuditLogger, PolicyEvaluationRecord
from agentops.security.context import SecurityContext
from agentops.security.decision import PolicyDecision
from agentops.security.policy import PolicyEngine
from agentops.security.requests import ActionRequest
from agentops.observability.tracing import start_span

logger = logging.getLogger("agentops.security.gateway")


class SecurityGateway:
    """
    Authorizing Security Gateway positioned between the SRE Agent and MCP Execution.
    Evaluates ActionRequests with PolicyEngine, coordinates ApprovalManager workflows,
    and enforces strict re-validation, pre-snapshots, verification, and replay protection.
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        audit_logger: Optional[AuditLogger] = None,
        approval_manager: Optional[ApprovalManager] = None,
        remediation_client: Optional[KubernetesRemediationClient] = None,
        metrics_tracker: Optional[RemediationMetricsTracker] = None,
    ):
        self.policy_engine = policy_engine or PolicyEngine()
        self.audit_logger = audit_logger or AuditLogger()
        self.approval_manager = approval_manager or ApprovalManager()
        self.remediation_client = remediation_client or KubernetesRemediationClient()
        self.metrics_tracker = metrics_tracker or RemediationMetricsTracker()

    def evaluate_request(
        self,
        security_context: SecurityContext,
        action_request: ActionRequest,
    ) -> PolicyDecision:
        """
        Evaluate an action request against the policy engine and record audit logs.
        """
        with start_span("agent.policy", attributes={"policy.action": action_request.action, "policy.agent_id": security_context.identity.agent_id}):
            decision = self.policy_engine.evaluate(security_context, action_request)

            # Record audit trail
            audit_record = PolicyEvaluationRecord(
                decision_id=decision.decision_id,
                request_id=action_request.request_id,
                agent_id=security_context.identity.agent_id,
                action=action_request.action,
                target=action_request.target.model_dump(),
                risk_level=decision.risk_level,
                decision=decision.decision,
                matched_policies=decision.matched_policies,
                violated_constraints=decision.violated_constraints,
                timestamp=decision.timestamp,
            )
            self.audit_logger.record(audit_record)
            return decision

    def execute_action(
        self,
        security_context: SecurityContext,
        action_request: ActionRequest,
        executor_callback: Optional[Callable[..., Any]] = None,
    ) -> Tuple[PolicyDecision, Optional[Any], Optional[ApprovalRequest]]:
        """
        Evaluate policy and conditionally execute if decision == ALLOW.
        For REQUIRE_APPROVAL, creates an ApprovalRequest and halts execution.
        For DENY, execution is strictly stopped.
        """
        decision = self.evaluate_request(security_context, action_request)

        if decision.decision == "DENY":
            logger.warning(
                f"[GATEWAY BLOCKED] Action '{action_request.action}' DENIED: {decision.reason}"
            )
            return decision, None, None

        if decision.decision == "REQUIRE_APPROVAL":
            logger.info(
                f"[GATEWAY APPROVAL REQUIRED] Action '{action_request.action}' requires human authorization. Creating pending approval."
            )
            approval = self.approval_manager.create_approval(
                action_request=action_request,
                policy_decision=decision,
            )
            return decision, None, approval

        # ALLOW path
        logger.info(f"[GATEWAY ALLOWED] Action '{action_request.action}' permitted by policy.")
        result = None
        if executor_callback is not None:
            result = executor_callback()
        return decision, result, None

    def execute_approved_action(
        self,
        approval_id: str,
        security_context: SecurityContext,
        action_request: ActionRequest,
        executor_callback: Optional[Callable[..., Any]] = None,
    ) -> Tuple[PolicyDecision, Optional[Any]]:
        """
        Re-validates an approved request against security context, policy, expiration,
        request binding, and single-use replay protection before permitting execution.
        """
        approval = self.approval_manager.get_approval(approval_id)
        if not approval:
            deny_dec = PolicyDecision(
                decision_id=f"dec-deny-{approval_id}",
                decision="DENY",
                reason=f"Approval request '{approval_id}' not found in storage",
                risk_level="CRITICAL",
                violated_constraints=["approval_not_found"],
            )
            return deny_dec, None

        if approval.is_expired() or approval.status == "EXPIRED":
            deny_dec = PolicyDecision(
                decision_id=f"dec-deny-{approval_id}",
                decision="DENY",
                reason=f"Approval request '{approval_id}' has expired and cannot be executed",
                risk_level=approval.policy_decision.risk_level,
                violated_constraints=["approval_expired"],
            )
            return deny_dec, None

        if approval.status == "CONSUMED":
            deny_dec = PolicyDecision(
                decision_id=f"dec-deny-{approval_id}",
                decision="DENY",
                reason=f"Approval request '{approval_id}' has already been consumed (replay attempt blocked)",
                risk_level="CRITICAL",
                violated_constraints=["approval_already_consumed"],
            )
            return deny_dec, None

        if approval.status != "APPROVED":
            deny_dec = PolicyDecision(
                decision_id=f"dec-deny-{approval_id}",
                decision="DENY",
                reason=f"Approval request '{approval_id}' is not in APPROVED state (current status: '{approval.status}')",
                risk_level=approval.policy_decision.risk_level,
                violated_constraints=[f"invalid_approval_status:{approval.status}"],
            )
            return deny_dec, None

        # Request Binding Verification
        orig_req = approval.action_request
        if (
            orig_req.request_id != action_request.request_id
            or orig_req.action != action_request.action
            or orig_req.target.model_dump() != action_request.target.model_dump()
            or orig_req.evidence_refs != action_request.evidence_refs
        ):
            deny_dec = PolicyDecision(
                decision_id=f"dec-deny-{approval_id}",
                decision="DENY",
                reason="ActionRequest parameters or evidence references do not match approved request binding",
                risk_level="CRITICAL",
                violated_constraints=["request_binding_mismatch"],
            )
            return deny_dec, None

        # Re-evaluate live policy & capability state
        re_eval_decision = self.policy_engine.evaluate(security_context, action_request)
        if re_eval_decision.decision == "DENY":
            deny_dec = PolicyDecision(
                decision_id=f"dec-deny-{approval_id}",
                decision="DENY",
                reason=f"Live policy or capability evaluation failed upon execution: {re_eval_decision.reason}",
                risk_level=re_eval_decision.risk_level,
                violated_constraints=re_eval_decision.violated_constraints,
            )
            return deny_dec, None

        # Single-use Replay Protection: Consume the approval
        self.approval_manager.consume(approval_id)

        # Log authorization execution audit record
        audit_record = PolicyEvaluationRecord(
            decision_id=f"dec-exec-{approval_id}",
            request_id=action_request.request_id,
            agent_id=security_context.identity.agent_id,
            action=action_request.action,
            target=action_request.target.model_dump(),
            risk_level=approval.policy_decision.risk_level,
            decision="ALLOW",
            matched_policies=approval.policy_decision.matched_policies + [f"approved_by:{approval.decided_by}"],
            violated_constraints=[],
            timestamp=approval.requested_at,
        )
        self.audit_logger.record(audit_record)

        # Execute callback
        logger.info(
            f"[GATEWAY EXECUTED] Approved action '{action_request.action}' executed successfully (Authorized by '{approval.decided_by}')"
        )
        result = None
        if executor_callback is not None:
            result = executor_callback()

        exec_decision = PolicyDecision(
            decision_id=f"dec-exec-{approval_id}",
            decision="ALLOW",
            reason=f"Action '{action_request.action}' authorized by human operator '{approval.decided_by}' (Approval: {approval_id})",
            risk_level=approval.policy_decision.risk_level,
            matched_policies=approval.policy_decision.matched_policies,
            required_approval=False,
        )
        return exec_decision, result

    def execute_remediation(
        self,
        security_context: SecurityContext,
        action_request: ActionRequest,
        approval_id: Optional[str] = None,
        dry_run: bool = False,
        timeout_seconds: int = 120,
    ) -> RemediationResult:
        """
        Executes end-to-end controlled remediation with pre-snapshots, verification,
        and full metrics/audit logging.
        """
        start_time = time.time()
        started_at = datetime.now(timezone.utc).isoformat()
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"

        target = action_request.target
        ns = target.namespace
        dep = target.resource_name
        action = action_request.action

        # Capture pre-remediation snapshot if possible
        pre_snapshot = None
        try:
            pre_snapshot = self.remediation_client.get_workload_snapshot(namespace=ns, deployment=dep)
        except Exception as e:
            logger.warning(f"Could not capture pre-remediation snapshot: {str(e)}")

        # -------------------------------------------------------------
        # 1. Dry Run Mode
        # -------------------------------------------------------------
        if dry_run:
            decision = self.evaluate_request(security_context, action_request)
            completed_at = datetime.now(timezone.utc).isoformat()
            duration = time.time() - start_time
            self.metrics_tracker.record_execution(action, "DRY_RUN", duration)

            return RemediationResult(
                execution_id=exec_id,
                request_id=action_request.request_id,
                approval_id=approval_id,
                action=action,
                target=target.model_dump(),
                status="DRY_RUN",
                pre_snapshot=pre_snapshot,
                post_verification=None,
                started_at=started_at,
                completed_at=completed_at,
                error=None,
                details={
                    "plan": f"WOULD EXECUTE '{action}' on '{ns}/{dep}'",
                    "policy_decision": decision.model_dump(),
                },
            )

        # -------------------------------------------------------------
        # 2. Real Remediation Execution (Requires Approval ID)
        # -------------------------------------------------------------
        if not approval_id:
            # Route to standard gateway evaluation (which creates an approval request)
            decision, _, approval = self.execute_action(security_context, action_request)
            completed_at = datetime.now(timezone.utc).isoformat()
            duration = time.time() - start_time
            self.metrics_tracker.record_execution(action, "BLOCKED", duration)

            return RemediationResult(
                execution_id=exec_id,
                request_id=action_request.request_id,
                approval_id=approval.approval_id if approval else None,
                action=action,
                target=target.model_dump(),
                status="BLOCKED",
                pre_snapshot=pre_snapshot,
                post_verification=None,
                started_at=started_at,
                completed_at=completed_at,
                error="Remediation requires human approval prior to execution",
                details={
                    "policy_decision": decision.model_dump(),
                    "approval_id": approval.approval_id if approval else None,
                },
            )

        # Execution callback for Kubernetes mutation
        mutation_details = {}

        def _do_remediation():
            nonlocal mutation_details
            if action == "k8s.remediation.restart_deployment":
                mutation_details = self.remediation_client.restart_deployment(
                    namespace=ns, deployment=dep, reason=action_request.reason
                )
            elif action == "k8s.remediation.scale_deployment":
                reps = target.parameters.get("replicas", 1)
                mutation_details = self.remediation_client.scale_deployment(
                    namespace=ns, deployment=dep, replicas=reps
                )
            elif action == "k8s.remediation.rollback_deployment":
                rev = target.parameters.get("revision")
                mutation_details = self.remediation_client.rollback_deployment(
                    namespace=ns, deployment=dep, revision=rev
                )
            else:
                raise ValueError(f"Unsupported remediation action: {action}")
            return mutation_details

        # Execute approved action through security gateway
        with start_span("agent.remediation", attributes={"remediation.action": action, "kubernetes.deployment": dep, "approval.id": approval_id or ""}):
            exec_decision, exec_raw = self.execute_approved_action(
                approval_id=approval_id,
                security_context=security_context,
                action_request=action_request,
                executor_callback=_do_remediation,
            )

        if exec_decision.decision != "ALLOW":
            completed_at = datetime.now(timezone.utc).isoformat()
            duration = time.time() - start_time
            self.metrics_tracker.record_execution(action, "BLOCKED", duration)

            return RemediationResult(
                execution_id=exec_id,
                request_id=action_request.request_id,
                approval_id=approval_id,
                action=action,
                target=target.model_dump(),
                status="BLOCKED",
                pre_snapshot=pre_snapshot,
                post_verification=None,
                started_at=started_at,
                completed_at=completed_at,
                error=exec_decision.reason,
                details={"policy_decision": exec_decision.model_dump()},
            )

        # Post-remediation Verification
        expected_reps = target.parameters.get("replicas") if action == "k8s.remediation.scale_deployment" else None
        with start_span("agent.verification", attributes={"kubernetes.namespace": ns, "kubernetes.deployment": dep}):
            verification = self.remediation_client.verify_workload_health(
                namespace=ns,
                deployment=dep,
                expected_replicas=expected_reps,
                timeout_seconds=timeout_seconds,
            )

        completed_at = datetime.now(timezone.utc).isoformat()
        duration = time.time() - start_time
        final_status = "SUCCESS" if verification.healthy else "FAILED"
        self.metrics_tracker.record_execution(action, final_status, duration)

        return RemediationResult(
            execution_id=exec_id,
            request_id=action_request.request_id,
            approval_id=approval_id,
            action=action,
            target=target.model_dump(),
            status=final_status,
            pre_snapshot=pre_snapshot,
            post_verification=verification,
            started_at=started_at,
            completed_at=completed_at,
            error=None if verification.healthy else "Post-remediation verification failed or timed out",
            details={
                "mutation": mutation_details,
                "verification": verification.model_dump(),
            },
        )
