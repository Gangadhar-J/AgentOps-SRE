from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from agentops.agent.investigator import SREAgent
from agentops.llm.base import BaseLLMProvider
from agentops.llm.gemini import GeminiLLMProvider
from agentops.llm.mock_provider import MockRuleBasedLLMProvider
from agentops.llm.openai_provider import OpenAILLMProvider
from agentops.config import settings
from agentops.models.rca import IncidentType, RootCauseAnalysis
from agentops.observability.tracing import start_span
from agentops.security.approval import ApprovalManager
from agentops.security.capabilities import Capability, CapabilityConstraints
from agentops.security.context import SecurityContext
from agentops.security.gateway import SecurityGateway
from agentops.security.identity import AgentIdentity
from agentops.security.operator import OperatorIdentity
from agentops.security.requests import ActionRequest, ActionTarget

from agentops.incident.models import EvidenceDetail, IncidentReport, IncidentSource, LLMRuntime, RemediationExecutionSummary

logger = logging.getLogger("agentops.incident")


class IncidentWorkflowManager:
    """
    High-Level Incident Workflow Orchestrator for SRE Operators.
    Exposes unified investigation, policy risk evaluation, human approval,
    and post-remediation rollout verification without bypassing SecurityGateway.
    """

    def __init__(
        self,
        gateway: Optional[SecurityGateway] = None,
        approval_manager: Optional[ApprovalManager] = None,
    ):
        self.gateway = gateway or SecurityGateway()
        self.approval_manager = approval_manager or self.gateway.approval_manager
        self._active_incident: Optional[IncidentReport] = None
        self._last_execution: Optional[RemediationExecutionSummary] = None

    def _get_provider(self, provider_name: str, model_name: Optional[str] = None) -> BaseLLMProvider:
        if provider_name == "gemini":
            return GeminiLLMProvider(model_name=model_name or "gemini-2.5-pro")
        elif provider_name == "openai":
            return OpenAILLMProvider(model_name=model_name or "gpt-4o")
        elif provider_name == "ollama":
            return OpenAILLMProvider(base_url=f"{settings.OLLAMA_URL}/v1", model_name=model_name or "qwen3.5:2b")
        else:
            return MockRuleBasedLLMProvider(model_name=model_name or "deterministic-rule-engine-v1")

    def _map_rca_to_action(
        self,
        incident_type: IncidentType,
        workload: str,
        namespace: str,
        rca: RootCauseAnalysis,
    ) -> tuple[str, str, Dict[str, Any]]:
        """
        Map RootCauseAnalysis to a concrete policy-governed remediation action.
        Returns: (action_name, human_readable_recommendation, target_parameters)
        """
        itype_val = incident_type.value if hasattr(incident_type, "value") else str(incident_type)

        if "CrashLoop" in itype_val:
            return (
                "k8s.remediation.restart_deployment",
                f"Restart deployment {namespace}/{workload}",
                {},
            )
        elif "Resource" in itype_val or "OOM" in itype_val:
            return (
                "k8s.remediation.scale_deployment",
                f"Scale deployment {namespace}/{workload} to 3 replicas",
                {"replicas": 3},
            )
        elif "BadDeployment" in itype_val or "Bad" in itype_val:
            return (
                "k8s.remediation.rollback_deployment",
                f"Rollback deployment {namespace}/{workload} to previous revision",
                {"revision": 1},
            )
        elif "HighErrorRate" in itype_val:
            return (
                "k8s.remediation.restart_deployment",
                f"Restart deployment {namespace}/{workload}",
                {},
            )
        else:
            return (
                "k8s.remediation.restart_deployment",
                f"Restart deployment {namespace}/{workload}",
                {},
            )

    def investigate_and_recommend(
        self,
        namespace: str = "demo",
        workload: str = "demo-app",
        incident_description: Optional[str] = None,
        provider_name: str = "mock",
        model_name: Optional[str] = None,
        dry_run: bool = False,
        source: IncidentSource = "MANUAL",
    ) -> IncidentReport:
        """
        Run end-to-end investigation, produce RCA, evaluate security policy,
        and generate pending approval if required.
        """
        start_time = time.time()
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"

        with start_span("agent.incident", attributes={"incident.id": incident_id, "incident.namespace": namespace, "incident.workload": workload, "dry_run": dry_run, "source": source}):
            llm_provider = self._get_provider(provider_name, model_name)
            agent = SREAgent(llm_provider=llm_provider)

            logger.info(f"Investigating workload '{workload}' in namespace '{namespace}' (Incident: {incident_id}, Source: {source}, Provider: {provider_name})")
            rca = agent.investigate(
                namespace=namespace,
                workload=workload,
                incident_description=incident_description,
            )

            # Summarize Evidence Telemetry
            context = getattr(agent, "last_context", None)
            evidence_summary = {"kubernetes": 0, "prometheus": 0, "loki": 0, "total": 0}
            evidence_items: List[EvidenceDetail] = []

            if context and context.evidence_items:
                for item in context.evidence_items:
                    src = item.source.value.lower() if hasattr(item.source, "value") else str(item.source).lower()
                    if src in evidence_summary:
                        evidence_summary[src] += 1
                    else:
                        evidence_summary[src] = 1
                    evidence_summary["total"] += 1

                    evidence_items.append(
                        EvidenceDetail(
                            id=item.id,
                            source=src,
                            resource=item.resource,
                            metric_or_query=item.metric_or_query,
                            observation=item.observation,
                            severity=item.severity,
                        )
                    )

            # Capture Provider-Neutral LLM Runtime Telemetry
            llm_runtime = None
            if rca and rca.agent_metrics:
                m = rca.agent_metrics
                p_tok = m.prompt_tokens
                c_tok = m.completion_tokens
                tot_tok = (p_tok + c_tok) if (p_tok is not None and c_tok is not None) else None
                dur = m.llm_latency_seconds
                tps = round(c_tok / dur, 1) if (c_tok is not None and dur > 0.05) else None

                actual_provider = m.llm_provider if (m.llm_provider and m.llm_provider != "unknown") else provider_name
                actual_model = m.llm_model if (m.llm_model and m.llm_model != "unknown") else (model_name or provider_name)

                is_fallback = bool(m.errors) or (provider_name != "mock" and actual_provider == "mock")
                if is_fallback:
                    mode_str = "rule-engine (fallback)"
                    err_hint = m.errors[0] if m.errors else "Primary provider failed"
                    status_str = f"FALLBACK ({err_hint[:50]})"
                else:
                    mode_str = "local" if actual_provider == "ollama" else ("rule-engine" if actual_provider == "mock" else "cloud")
                    status_str = "READY"

                llm_runtime = LLMRuntime(
                    provider=actual_provider,
                    model=actual_model,
                    mode=mode_str,
                    latency_seconds=round(dur, 3),
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    total_tokens=tot_tok,
                    tokens_per_second=tps,
                    status=status_str,
                )

            # Map RCA to policy-governed remediation action
            action_name, rec_text, params = self._map_rca_to_action(
                incident_type=rca.incident_type,
                workload=workload,
                namespace=namespace,
                rca=rca,
            )

            # Create standard ActionRequest
            action_req_id = f"req-{uuid.uuid4().hex[:8]}"
            target = ActionTarget(
                namespace=namespace,
                resource_type="deployment",
                resource_name=workload,
                parameters=params,
            )
            reason_text = rca.root_cause
            if len(reason_text.strip()) < 10:
                reason_text = f"Controlled remediation for incident in {namespace}/{workload}"

            action_request = ActionRequest(
                request_id=action_req_id,
                action=action_name,
                target=target,
                reason=reason_text,
                evidence_refs=rca.evidence_ids if rca.evidence_ids else ["E001"],
            )

            # Build Security Context with granted capabilities for target resource
            identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.7.1")
            allowed_ns = list(set(["demo", namespace]))
            allowed_res = list(set(["demo-app", workload]))
            caps = (
                Capability(
                    name="k8s.remediation.restart_deployment",
                    resource="deployment",
                    constraints=CapabilityConstraints(namespaces=allowed_ns, allowed_resources=allowed_res),
                ),
                Capability(
                    name="k8s.remediation.scale_deployment",
                    resource="deployment",
                    constraints=CapabilityConstraints(namespaces=allowed_ns, allowed_resources=allowed_res, max_replicas=10),
                ),
                Capability(
                    name="k8s.remediation.rollback_deployment",
                    resource="deployment",
                    constraints=CapabilityConstraints(namespaces=allowed_ns, allowed_resources=allowed_res),
                ),
            )
            sec_ctx = SecurityContext(identity=identity, capabilities=caps, request_id=action_req_id)

            # Policy & Gateway Evaluation
            policy_decision_str = "ALLOW"
            policy_reason = None
            risk_level = "LOW"
            approval_required = False
            approval_id = None
            status = "INVESTIGATED"

            if dry_run:
                # In dry-run mode: evaluate policy without creating persistent approvals or mutations
                eval_dec = self.gateway.policy_engine.evaluate(sec_ctx, action_request)
                policy_decision_str = eval_dec.decision
                policy_reason = eval_dec.reason
                risk_level = eval_dec.risk_level
                approval_required = (eval_dec.decision == "REQUIRE_APPROVAL")
                status = "DRY_RUN_EVALUATED"
            else:
                decision, _, approval = self.gateway.execute_action(sec_ctx, action_request)
                policy_decision_str = decision.decision
                policy_reason = decision.reason
                risk_level = decision.risk_level

                if decision.decision == "REQUIRE_APPROVAL":
                    approval_required = True
                    approval_id = approval.approval_id if approval else None
                    status = "PENDING_APPROVAL"
                elif decision.decision == "DENY":
                    status = "BLOCKED"
                else:
                    status = "AUTHORIZED"

            duration = round(time.time() - start_time, 2)
            report = IncidentReport(
                incident_id=incident_id,
                namespace=namespace,
                workload=workload,
                status=status,
                source=source,
                incident_type=rca.incident_type.value if hasattr(rca.incident_type, "value") else str(rca.incident_type),
                confidence=round(rca.confidence, 2),
                summary=rca.summary,
                root_cause=rca.root_cause,
                llm_runtime=llm_runtime,
                evidence_summary=evidence_summary,
                evidence_items=evidence_items,
                recommended_remediation=rec_text,
                recommended_action=action_name,
                risk_level=risk_level,
                policy_decision=policy_decision_str,
                policy_reason=policy_reason,
                approval_required=approval_required,
                approval_id=approval_id,
                action_request_id=action_req_id,
                duration_seconds=duration,
            )

            self._active_incident = report
            return report

    def approve_and_execute(
        self,
        approval_id: str,
        operator_name: str = "local-sre",
        reason: str = "Operator validated RCA and authorized remediation",
    ) -> RemediationExecutionSummary:
        """
        Authorize a pending approval and execute the remediation through SecurityGateway.
        Performs single-use token validation, mutation, and post-verification.
        """
        approval = self.approval_manager.get_approval(approval_id)
        if not approval:
            raise ValueError(f"Approval request '{approval_id}' not found")

        with start_span("agent.incident.execution", attributes={"approval.id": approval_id, "operator": operator_name}):
            # 1. Authorize via ApprovalManager
            operator = OperatorIdentity(operator_id=operator_name, display_name=operator_name.title())
            self.approval_manager.approve(approval_id, operator, reason=reason)

            # 2. Reconstruct SecurityContext with agent identity
            action_request = approval.action_request
            identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.7.1")
            target_ns = action_request.target.namespace
            target_res = action_request.target.resource_name
            allowed_ns = list(set(["demo", target_ns]))
            allowed_res = list(set(["demo-app", target_res]))
            caps = (
                Capability(
                    name="k8s.remediation.restart_deployment",
                    resource="deployment",
                    constraints=CapabilityConstraints(namespaces=allowed_ns, allowed_resources=allowed_res),
                ),
                Capability(
                    name="k8s.remediation.scale_deployment",
                    resource="deployment",
                    constraints=CapabilityConstraints(namespaces=allowed_ns, allowed_resources=allowed_res, max_replicas=10),
                ),
                Capability(
                    name="k8s.remediation.rollback_deployment",
                    resource="deployment",
                    constraints=CapabilityConstraints(namespaces=allowed_ns, allowed_resources=allowed_res),
                ),
            )
            sec_ctx = SecurityContext(identity=identity, capabilities=caps, request_id=action_request.request_id)

            # 3. Controlled Execution via SecurityGateway
            rem_result = self.gateway.execute_remediation(
                security_context=sec_ctx,
                action_request=action_request,
                approval_id=approval_id,
            )

            # 4. Extract verification outcomes
            post_verif = rem_result.post_verification
            rollout_status = "NOT_APPLICABLE"
            ready_reps = None
            desired_reps = None
            resolution_status = "FAILED"

            if post_verif:
                rollout_status = "HEALTHY" if post_verif.healthy else "DEGRADED"
                ready_reps = post_verif.observations.get("ready_replicas")
                desired_reps = post_verif.observations.get("desired_replicas") or post_verif.observations.get("expected_replicas")
                if post_verif.healthy and rem_result.status == "SUCCESS":
                    resolution_status = "RESOLVED"

            verif_dict = post_verif.model_dump() if post_verif else None

            summary = RemediationExecutionSummary(
                execution_id=rem_result.execution_id,
                approval_id=approval_id,
                action=rem_result.action,
                target=rem_result.target,
                authorization_status="AUTHORIZED",
                mutation_status=rem_result.status,
                rollout_status=rollout_status,
                ready_replicas=ready_reps,
                desired_replicas=desired_reps,
                resolution_status=resolution_status,
                verification_result=verif_dict,
                details=rem_result.details,
            )

            self._last_execution = summary
            if self._active_incident and self._active_incident.approval_id == approval_id:
                # Update in-memory active incident status
                object.__setattr__(self._active_incident, "status", resolution_status)

            return summary

    def reject(
        self,
        approval_id: str,
        operator_name: str = "local-sre",
        reason: str = "Remediation rejected by operator",
    ) -> Dict[str, Any]:
        """Reject a pending approval without infrastructure mutation."""
        operator = OperatorIdentity(operator_id=operator_name, display_name=operator_name.title())
        rejection = self.approval_manager.reject(approval_id, operator, reason=reason)
        if self._active_incident and self._active_incident.approval_id == approval_id:
            object.__setattr__(self._active_incident, "status", "REJECTED")

        return {
            "approval_id": approval_id,
            "status": "REJECTED",
            "decided_by": operator_name,
            "reason": reason,
            "rejected_at": rejection.decided_at,
        }

    def get_active_incident(self) -> Optional[IncidentReport]:
        return self._active_incident

    def get_last_execution(self) -> Optional[RemediationExecutionSummary]:
        return self._last_execution

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        approvals = self.approval_manager.list_pending()
        return [a.model_dump() for a in approvals]
