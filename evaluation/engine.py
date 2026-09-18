from datetime import datetime, timezone
import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Literal, Optional
import uuid
import yaml

from agentops.agent.investigator import SREAgent
from agentops.config import settings
from agentops.llm.base import BaseLLMProvider
from agentops.llm.mock_provider import MockRuleBasedLLMProvider
from agentops.models.evidence import (
    EvidenceItem,
    EvidenceType,
    InvestigationContext,
    TelemetrySource,
    TelemetryStatus,
)
from agentops.models.rca import IncidentType, RootCauseAnalysis
from agentops.models.remediation import RemediationResult, RemediationVerification
from agentops.security.approval import ApprovalManager
from agentops.security.capabilities import Capability, CapabilityConstraints
from agentops.security.context import SecurityContext
from agentops.security.decision import PolicyDecision
from agentops.security.gateway import SecurityGateway
from agentops.security.identity import AgentIdentity
from agentops.security.operator import OperatorIdentity
from agentops.security.policy import PolicyEngine
from agentops.security.requests import ActionRequest, ActionTarget

from agentops.observability.tracing import start_span
from evaluation.evaluators.efficiency_evaluator import EfficiencyEvaluator
from evaluation.evaluators.evidence_evaluator import EvidenceEvaluator
from evaluation.evaluators.policy_evaluator import PolicyComplianceEvaluator
from evaluation.evaluators.rca_evaluator import RCAEvaluator
from evaluation.evaluators.remediation_evaluator import RemediationEvaluator
from evaluation.evaluators.safety_evaluator import SafetyEvaluator
from evaluation.evaluators.tool_evaluator import ToolSelectionEvaluator
from evaluation.evaluators.verification_evaluator import VerificationEvaluator
from evaluation.models import (
    EvaluationResult,
    EvaluationRunMetadata,
    EvaluationRunSummary,
    EvaluationScores,
    ScenarioDefinition,
    compute_config_hash,
)
from evaluation.scoring import WeightedScorer

logger = logging.getLogger("agentops.evaluation")


class EvaluationEngine:
    """
    Core Evaluation Engine for AgentOps-SRE.
    Executes benchmark scenarios in either REPLAY mode (fast, deterministic, zero-cluster)
    or LIVE mode (end-to-end against live Kind cluster).
    """

    def __init__(
        self,
        scenarios_dir: Optional[str] = None,
        replays_dir: Optional[str] = None,
        scorer: Optional[WeightedScorer] = None,
    ):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.scenarios_dir = scenarios_dir or os.path.join(base_dir, "evaluation", "scenarios")
        self.replays_dir = replays_dir or os.path.join(base_dir, "evaluation", "replays")
        self.scorer = scorer or WeightedScorer()

        # Evaluators
        self.rca_evaluator = RCAEvaluator()
        self.evidence_evaluator = EvidenceEvaluator()
        self.tool_evaluator = ToolSelectionEvaluator()
        self.policy_evaluator = PolicyComplianceEvaluator()
        self.remediation_evaluator = RemediationEvaluator()
        self.verification_evaluator = VerificationEvaluator()
        self.safety_evaluator = SafetyEvaluator()
        self.efficiency_evaluator = EfficiencyEvaluator()

    def discover_scenarios(self) -> List[str]:
        """Discover all available scenario IDs across scenarios directory."""
        scenario_ids = []
        if not os.path.exists(self.scenarios_dir):
            return scenario_ids

        for root, _, files in os.walk(self.scenarios_dir):
            for f in sorted(files):
                if f.endswith(".yaml") or f.endswith(".yml"):
                    try:
                        with open(os.path.join(root, f), "r", encoding="utf-8") as fp:
                            data = yaml.safe_load(fp)
                        if data and "scenario_id" in data:
                            scenario_ids.append(data["scenario_id"])
                    except Exception as e:
                        logger.warning(f"Failed to read scenario file {f}: {str(e)}")
        return scenario_ids

    def load_scenario(self, scenario_id: str) -> ScenarioDefinition:
        """Load and validate scenario definition by scenario_id or base name."""
        clean_id = scenario_id.replace(".yaml", "").replace(".yml", "")
        candidates = [
            clean_id,
            f"{clean_id}-001",
            clean_id.replace("-", "_"),
            clean_id.replace("_", "-"),
            f"{clean_id.replace('_', '-')}-001",
        ]
        for root, _, files in os.walk(self.scenarios_dir):
            for f in sorted(files):
                if f.endswith(".yaml") or f.endswith(".yml"):
                    filepath = os.path.join(root, f)
                    try:
                        with open(filepath, "r", encoding="utf-8") as fp:
                            data = yaml.safe_load(fp)
                        if data:
                            sid = data.get("scenario_id", "")
                            file_stem = f.rsplit(".", 1)[0]
                            if sid in candidates or file_stem in candidates:
                                return ScenarioDefinition(**data)
                    except Exception as e:
                        logger.warning(f"Error parsing {filepath}: {str(e)}")
        raise FileNotFoundError(f"Scenario definition '{scenario_id}' not found in {self.scenarios_dir}")

    def load_replay_fixture(self, scenario_id: str) -> Dict[str, Any]:
        """Load replay fixture json for deterministic evaluation."""
        base_name = scenario_id.split("-001")[0]
        candidates = [
            f"{base_name}.json",
            f"{base_name.replace('-', '_')}.json",
            f"{base_name.replace('_', '-')}.json",
            f"{scenario_id}.json",
            f"{scenario_id.replace('-', '_')}.json",
        ]
        for c in candidates:
            fixture_path = os.path.join(self.replays_dir, c)
            if os.path.exists(fixture_path):
                with open(fixture_path, "r", encoding="utf-8") as fp:
                    return json.load(fp)

        raise FileNotFoundError(f"Replay fixture for scenario '{scenario_id}' not found in {self.replays_dir}")

    def _get_provider(self, provider_name: str, model_name: Optional[str] = None) -> BaseLLMProvider:
        """Instantiate configured LLM provider."""
        if provider_name == "gemini":
            from agentops.llm.gemini import GeminiLLMProvider
            return GeminiLLMProvider(model_name=model_name or "gemini-2.5-pro")
        elif provider_name == "openai":
            from agentops.llm.openai_provider import OpenAILLMProvider
            return OpenAILLMProvider(model_name=model_name or "gpt-4o")
        else:
            return MockRuleBasedLLMProvider(model_name=model_name or "deterministic-rule-engine-v1")

    def run_scenario(
        self,
        scenario_id: str,
        mode: Literal["live", "replay"] = "replay",
        provider_name: str = "mock",
        model_name: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> EvaluationResult:
        """
        Run evaluation for a single scenario in either replay or live mode.
        """
        scenario = self.load_scenario(scenario_id)
        current_run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        eval_id = f"eval-{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        llm_provider = self._get_provider(provider_name, model_name)
        actual_model = getattr(llm_provider, "model_name", provider_name)

        with start_span("agent.evaluation", attributes={"evaluation.scenario_id": scenario.scenario_id, "evaluation.mode": mode, "evaluation.provider": provider_name, "evaluation.run_id": current_run_id}):
            if mode == "replay":
                return self._execute_replay_scenario(
                    scenario=scenario,
                    llm_provider=llm_provider,
                    run_id=current_run_id,
                    eval_id=eval_id,
                    provider_name=provider_name,
                    model_name=actual_model,
                    start_time=start_time,
                )
            else:
                return self._execute_live_scenario(
                    scenario=scenario,
                    llm_provider=llm_provider,
                    run_id=current_run_id,
                    eval_id=eval_id,
                    provider_name=provider_name,
                    model_name=actual_model,
                    start_time=start_time,
                )

    def _execute_replay_scenario(
        self,
        scenario: ScenarioDefinition,
        llm_provider: BaseLLMProvider,
        run_id: str,
        eval_id: str,
        provider_name: str,
        model_name: str,
        start_time: float,
    ) -> EvaluationResult:
        """
        Deterministic, fast replay execution path (no cluster required).
        """
        fixture = self.load_replay_fixture(scenario.scenario_id)

        # 1. Reconstruct Investigation Context from fixture
        context = InvestigationContext(
            investigation_id=f"inv-replay-{scenario.scenario_id}",
            namespace=scenario.namespace,
            workload=scenario.workload,
        )

        for item_dict in fixture.get("evidence_items", []):
            item = EvidenceItem(
                id=item_dict["id"],
                source=TelemetrySource(item_dict["source"]),
                evidence_type=EvidenceType(item_dict.get("evidence_type", "FACT")),
                resource=item_dict["resource"],
                metric_or_query=item_dict["metric_or_query"],
                observation=item_dict["observation"],
                severity=item_dict.get("severity", "INFO"),
                raw_payload=item_dict.get("raw_payload"),
            )
            context.evidence_items.append(item)

        for src, status_dict in fixture.get("telemetry_status", {}).items():
            context.telemetry_status[src] = TelemetryStatus(
                source=TelemetrySource(src),
                available=status_dict.get("available", True),
                query_count=status_dict.get("query_count", 1),
            )

        # 2. Run LLM Reasoning to produce RCA
        rca, meta = llm_provider.generate_rca(context)

        # 3. Replay Tools Invoked
        invoked_tools = fixture.get("invoked_tools", [])

        # 4. Security Gateway Policy Evaluation
        gateway = SecurityGateway()
        policy_decision = None
        action_request = None
        remediation_result = None

        remed_spec = fixture.get("remediation")
        if remed_spec:
            target = ActionTarget(
                namespace=remed_spec.get("namespace", scenario.namespace),
                resource_type="deployment",
                resource_name=remed_spec.get("resource_name", scenario.workload),
                parameters=remed_spec.get("parameters", {}),
            )
            evidence_refs = [e.id for e in context.evidence_items[:2]] if context.evidence_items else ["E001"]
            action_request = ActionRequest(
                request_id=f"req-replay-{scenario.scenario_id}",
                action=remed_spec["action"],
                target=target,
                reason=remed_spec.get("reason", "Replay remediation evaluation"),
                evidence_refs=evidence_refs,
            )

            # Define agent context with granted demo capabilities
            identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.6.0")
            caps = (
                Capability(name="k8s.remediation.restart_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"])),
                Capability(name="k8s.remediation.scale_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"], max_replicas=5)),
                Capability(name="k8s.remediation.rollback_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"])),
            )
            sec_ctx = SecurityContext(identity=identity, capabilities=caps, request_id=action_request.request_id)

            policy_decision = gateway.evaluate_request(sec_ctx, action_request)

            # Simulate controlled execution if approved & expected
            if policy_decision.decision == "REQUIRE_APPROVAL" and scenario.expected_mutation:
                verif_dict = fixture.get("verification", {})
                verif = RemediationVerification(
                    healthy=verif_dict.get("healthy", True),
                    checks=verif_dict.get("checks", ["rollout_complete"]),
                    failed_checks=verif_dict.get("failed_checks", []),
                    observations=verif_dict.get("observations", {}),
                )
                remediation_result = RemediationResult(
                    execution_id=f"exec-replay-{scenario.scenario_id}",
                    request_id=action_request.request_id,
                    approval_id="appr-mock-authorized",
                    action=action_request.action,
                    target=action_request.target.model_dump(),
                    status="SUCCESS" if verif.healthy else "FAILED",
                    post_verification=verif,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
            elif policy_decision.decision == "DENY":
                remediation_result = RemediationResult(
                    execution_id=f"exec-replay-{scenario.scenario_id}",
                    request_id=action_request.request_id,
                    action=action_request.action,
                    target=action_request.target.model_dump(),
                    status="BLOCKED",
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    error=policy_decision.reason,
                )

        duration = time.time() - start_time

        # 5. Evaluate all dimensions
        return self._evaluate_and_build_result(
            scenario=scenario,
            rca=rca,
            context=context,
            invoked_tools=invoked_tools,
            policy_decision=policy_decision,
            action_request=action_request,
            remediation_result=remediation_result,
            duration_seconds=duration,
            run_id=run_id,
            eval_id=eval_id,
            mode="replay",
            provider_name=provider_name,
            model_name=model_name,
            infrastructure_mutated=False,  # Replay mode NEVER mutates cluster
            unexpected_mutation=False,
            mutation_count=0,
            meta=meta,
        )

    def _execute_live_scenario(
        self,
        scenario: ScenarioDefinition,
        llm_provider: BaseLLMProvider,
        run_id: str,
        eval_id: str,
        provider_name: str,
        model_name: str,
        start_time: float,
    ) -> EvaluationResult:
        """
        Live execution path against live Kind cluster.
        """
        infrastructure_mutated = False
        unexpected_mutation = False
        mutation_count = 0

        # Step 1: Trigger incident if configured
        if scenario.trigger_action:
            try:
                subprocess.run(
                    ["./scripts/trigger-incident.sh", scenario.trigger_action],
                    check=True,
                    capture_output=True,
                )
                time.sleep(4)
            except Exception as e:
                logger.error(f"Failed to trigger incident '{scenario.trigger_action}': {str(e)}")

        # Step 2: Run SREAgent investigation over live MCP
        agent = SREAgent(llm_provider=llm_provider)
        context = None
        rca = None
        invoked_tools = []
        meta = {}

        try:
            rca = agent.investigate(namespace=scenario.namespace, workload=scenario.workload)
            # Retrieve context and tool invocation history from orchestrator
            if hasattr(agent.orchestrator, "mcp_client"):
                mcp_tracker = agent.orchestrator.mcp_client.metrics
                invoked_tools = [inv.tool_name for inv in mcp_tracker.invocations]
        except Exception as e:
            logger.error(f"Live investigation failed: {str(e)}")

        # Step 3: Handle remediation proposal & security gateway
        gateway = SecurityGateway()
        policy_decision = None
        action_request = None
        remediation_result = None

        if scenario.expected_remediation:
            exp_rem = scenario.expected_remediation
            req_id = f"req-live-{uuid.uuid4().hex[:8]}"
            target = ActionTarget(
                namespace=scenario.namespace,
                resource_type=exp_rem.resource_type,
                resource_name=exp_rem.resource_name,
                parameters=exp_rem.parameters,
            )
            evidence_refs = rca.evidence_ids if (rca and rca.evidence_ids) else ["E001"]
            action_request = ActionRequest(
                request_id=req_id,
                action=exp_rem.action,
                target=target,
                reason="Controlled remediation from scenario evaluation",
                evidence_refs=evidence_refs,
            )

            identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.6.0")
            caps = (
                Capability(name="k8s.remediation.restart_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"])),
                Capability(name="k8s.remediation.scale_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"], max_replicas=5)),
                Capability(name="k8s.remediation.rollback_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"])),
            )
            sec_ctx = SecurityContext(identity=identity, capabilities=caps, request_id=req_id)

            policy_decision = gateway.evaluate_request(sec_ctx, action_request)

            # If scenario permits mutation and approval is required, approve and execute
            if scenario.expected_mutation and policy_decision.decision == "REQUIRE_APPROVAL":
                approval_manager = gateway.approval_manager
                approval = approval_manager.create_approval(action_request, policy_decision)
                operator = OperatorIdentity(operator_id="eval-operator", display_name="Eval Test Operator")
                approval_manager.approve(approval.approval_id, operator, reason="Evaluation authorized execution")

                # Execute controlled remediation mutation
                remediation_result = gateway.execute_remediation(
                    security_context=sec_ctx,
                    action_request=action_request,
                    approval_id=approval.approval_id,
                )
                infrastructure_mutated = True
                mutation_count += 1
            elif not scenario.expected_mutation and policy_decision.decision == "DENY":
                remediation_result = RemediationResult(
                    execution_id=f"exec-live-{uuid.uuid4().hex[:8]}",
                    request_id=action_request.request_id,
                    action=action_request.action,
                    target=action_request.target.model_dump(),
                    status="BLOCKED",
                    started_at=datetime.now(timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    error=policy_decision.reason,
                )

        # Step 4: Reset cluster
        if scenario.trigger_action or infrastructure_mutated:
            try:
                subprocess.run(["./scripts/trigger-incident.sh", "reset"], check=True, capture_output=True)
                time.sleep(2)
            except Exception as e:
                logger.warning(f"Failed to reset cluster after scenario: {str(e)}")

        duration = time.time() - start_time

        # Check for unexpected mutation
        if infrastructure_mutated and not scenario.expected_mutation:
            unexpected_mutation = True

        return self._evaluate_and_build_result(
            scenario=scenario,
            rca=rca,
            context=getattr(agent, "last_context", None),
            invoked_tools=invoked_tools,
            policy_decision=policy_decision,
            action_request=action_request,
            remediation_result=remediation_result,
            duration_seconds=duration,
            run_id=run_id,
            eval_id=eval_id,
            mode="live",
            provider_name=provider_name,
            model_name=model_name,
            infrastructure_mutated=infrastructure_mutated,
            unexpected_mutation=unexpected_mutation,
            mutation_count=mutation_count,
            meta=meta,
        )

    def _evaluate_and_build_result(
        self,
        scenario: ScenarioDefinition,
        rca: Optional[RootCauseAnalysis],
        context: Optional[InvestigationContext],
        invoked_tools: List[str],
        policy_decision: Optional[PolicyDecision],
        action_request: Optional[ActionRequest],
        remediation_result: Optional[RemediationResult],
        duration_seconds: float,
        run_id: str,
        eval_id: str,
        mode: Literal["live", "replay"],
        provider_name: str,
        model_name: str,
        infrastructure_mutated: bool,
        unexpected_mutation: bool,
        mutation_count: int,
        meta: Dict[str, Any],
    ) -> EvaluationResult:
        """Run all evaluators, aggregate scores, and enforce deterministic safety overrides."""
        all_failures: List[str] = []

        # 1. RCA Evaluation
        rca_score, rca_fails = self.rca_evaluator.evaluate(scenario, rca)
        all_failures.extend(rca_fails)

        # 2. Evidence Evaluation
        ev_score, ev_fails, hallucination = self.evidence_evaluator.evaluate(scenario, rca, context)
        all_failures.extend(ev_fails)

        # 3. Tool Selection Evaluation
        tool_score, tool_fails, forbidden_tool = self.tool_evaluator.evaluate(scenario, invoked_tools)
        all_failures.extend(tool_fails)

        # 4. Policy Compliance Evaluation
        policy_score, policy_fails, bypass_attempt = self.policy_evaluator.evaluate(
            scenario, policy_decision, action_request
        )
        all_failures.extend(policy_fails)

        # 5. Remediation Correctness Evaluation
        rem_score, rem_fails = self.remediation_evaluator.evaluate(
            scenario, remediation_result, action_request
        )
        all_failures.extend(rem_fails)

        # 6. Verification Correctness Evaluation
        ver_score, ver_fails, false_success = self.verification_evaluator.evaluate(
            scenario, remediation_result
        )
        all_failures.extend(ver_fails)

        # 7. Safety Evaluation (Dedicated zero-tolerance safety assessor)
        safety_score, safety_violations, critical_safety_failure = self.safety_evaluator.evaluate(
            scenario=scenario,
            infrastructure_mutated=infrastructure_mutated,
            unexpected_mutation=unexpected_mutation,
            mutation_count=mutation_count,
            gateway_bypass_attempted=bypass_attempt,
            forbidden_tool_used=forbidden_tool,
            hallucination_detected=hallucination,
            false_success_detected=false_success,
        )
        all_failures.extend(safety_violations)

        # 8. Efficiency Evaluation
        eff_score, eff_fails, eff_metrics = self.efficiency_evaluator.evaluate(
            scenario=scenario,
            duration_seconds=duration_seconds,
            tool_call_count=len(invoked_tools),
            prompt_tokens=meta.get("prompt_tokens"),
            completion_tokens=meta.get("completion_tokens"),
        )
        all_failures.extend(eff_fails)

        scores = EvaluationScores(
            rca_accuracy=rca_score,
            evidence_accuracy=ev_score,
            tool_selection=tool_score,
            policy_compliance=policy_score,
            remediation_correctness=rem_score,
            verification_correctness=ver_score,
            safety=safety_score,
            efficiency=eff_score,
            overall_score=0.0,
        )

        overall, passed = self.scorer.compute_overall(
            scores=scores,
            critical_safety_failure=critical_safety_failure,
            unexpected_mutation=unexpected_mutation,
        )
        scores = scores.model_copy(update={"overall_score": overall})

        metrics = {
            **eff_metrics,
            "invoked_tools": invoked_tools,
            "infrastructure_mutated": infrastructure_mutated,
            "mutation_count": mutation_count,
        }

        # Config hash for provenance
        config_content = f"{scenario.scenario_id}:{scores.overall_score}:{self.scorer.weights}"
        cfg_hash = compute_config_hash(config_content)

        run_metadata = EvaluationRunMetadata(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            scenario_id=scenario.scenario_id,
            scenario_version=getattr(scenario, "scenario_version", "1.0.0"),
            agent_version="0.6.0",
            model=model_name,
            provider=provider_name,
            policy_version="0.4.0",
            evaluator_version="0.6.0",
            dataset_version="0.6.0",
            configuration_hash=cfg_hash,
        )

        return EvaluationResult(
            evaluation_id=eval_id,
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            run_id=run_id,
            mode=mode,
            provider=provider_name,
            model=model_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            scores=scores,
            passed=passed,
            overall_score=scores.overall_score,
            critical_safety_failure=critical_safety_failure,
            infrastructure_mutated=infrastructure_mutated,
            unexpected_mutation=unexpected_mutation,
            mutation_count=mutation_count,
            safety_violations=safety_violations,
            failures=all_failures,
            observations={"incident_type": rca.incident_type if rca else "None"},
            metrics=metrics,
            agent_version="0.6.0",
            evaluator_version="0.6.0",
            dataset_version="0.6.0",
            model_version="1.0.0",
            policy_version="0.4.0",
            scenario_version=getattr(scenario, "scenario_version", "1.0.0"),
            configuration_hash=cfg_hash,
            metadata=run_metadata,
        )

    def run_all(
        self,
        mode: Literal["live", "replay"] = "replay",
        provider_name: str = "mock",
        model_name: Optional[str] = None,
    ) -> EvaluationRunSummary:
        """Run all discovered benchmark scenarios and compute aggregated summary."""
        scenario_ids = self.discover_scenarios()
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        results: List[EvaluationResult] = []

        total_mutations = 0
        unexpected_mutations = 0
        critical_safety_failures = 0

        for sid in scenario_ids:
            logger.info(f"Running scenario '{sid}' [mode={mode}, provider={provider_name}]...")
            res = self.run_scenario(
                scenario_id=sid,
                mode=mode,
                provider_name=provider_name,
                model_name=model_name,
                run_id=run_id,
            )
            results.append(res)
            if res.infrastructure_mutated:
                total_mutations += res.mutation_count
            if res.unexpected_mutation:
                unexpected_mutations += 1
            if res.critical_safety_failure:
                critical_safety_failures += 1

        passed_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - passed_count
        avg_overall = round(sum(r.scores.overall_score for r in results) / max(len(results), 1), 4)

        all_passed = (failed_count == 0) and (critical_safety_failures == 0) and (unexpected_mutations == 0)

        return EvaluationRunSummary(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            mode=mode,
            provider=provider_name,
            model=model_name or provider_name,
            total_scenarios=len(results),
            passed_scenarios=passed_count,
            failed_scenarios=failed_count,
            overall_score=avg_overall,
            passed=all_passed,
            critical_safety_failures=critical_safety_failures,
            total_mutations=total_mutations,
            unexpected_mutations=unexpected_mutations,
            results=results,
        )
