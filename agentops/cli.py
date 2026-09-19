import argparse
import json
import logging
import sys
import uuid
from agentops.agent.investigator import SREAgent
from agentops.config import settings
from agentops.llm.gemini import GeminiLLMProvider
from agentops.llm.mock_provider import MockRuleBasedLLMProvider
from agentops.llm.openai_provider import OpenAILLMProvider
from agentops.security.approval import ApprovalManager
from agentops.security.capabilities import Capability, CapabilityConstraints
from agentops.security.context import SecurityContext
from agentops.security.gateway import SecurityGateway
from agentops.security.identity import AgentIdentity
from agentops.security.operator import OperatorIdentity
from agentops.security.policy import PolicyEngine
from agentops.security.requests import ActionRequest, ActionTarget

from agentops.incident.orchestrator import IncidentWorkflowManager
from agentops.api.app import create_app

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agentops.cli")


def handle_operator_incident(args):
    """
    Unified, single-command incident investigation and optional remediation for SRE operators.
    """
    target = args.target
    if "/" in target:
        namespace, workload = target.split("/", 1)
    else:
        namespace = getattr(args, "namespace", "demo") or "demo"
        workload = target

    workflow = IncidentWorkflowManager()
    logger.info(f"Investigating incident on {namespace}/{workload} (Provider: {args.provider}, DryRun: {args.dry_run})")

    report = workflow.investigate_and_recommend(
        namespace=namespace,
        workload=workload,
        incident_description=args.incident,
        provider_name=args.provider,
        model_name=args.model,
        dry_run=args.dry_run,
    )

    if args.json and not (args.auto or args.yes):
        print(report.model_dump_json(indent=2))
        return

    print("\n" + "=" * 70)
    print("              AGENTOPS SRE - INCIDENT INVESTIGATION REPORT")
    print("=" * 70)
    print(f"Incident ID:       {report.incident_id}")
    print(f"Status:            {report.status}")
    print(f"Source:            {report.source}")
    print(f"Workload:          {report.namespace}/{report.workload}")
    print(f"Incident Type:     {report.incident_type}")
    print(f"Confidence:        {report.confidence * 100:.1f}%")
    if report.llm_runtime:
        rt = report.llm_runtime
        tok_str = f"Prompt: {rt.prompt_tokens}, Compl: {rt.completion_tokens}, Total: {rt.total_tokens}" if rt.total_tokens is not None else "Tokens: N/A"
        tps_str = f" ({rt.tokens_per_second} tok/s)" if rt.tokens_per_second else ""
        print(f"AI Model Runtime:  {rt.provider} / {rt.model} [{rt.mode}] ({rt.latency_seconds:.2f}s, {tok_str}{tps_str})")
    print()

    print("-" * 70)
    print("ROOT CAUSE ANALYSIS")
    print("-" * 70)
    print(f"Summary:    {report.summary}")
    print(f"Root Cause: {report.root_cause}\n")

    print("-" * 70)
    print(f"CORRELATED TELEMETRY EVIDENCE ({len(report.evidence_items)} items, {report.duration_seconds}s)")
    print("-" * 70)
    print(f"  • Kubernetes: {report.evidence_summary.get('kubernetes', 0)} signal(s)")
    print(f"  • Prometheus: {report.evidence_summary.get('prometheus', 0)} signal(s)")
    print(f"  • Loki:       {report.evidence_summary.get('loki', 0)} signal(s)")
    for ev in report.evidence_items:
        print(f"    - [{ev.source.upper()}] {ev.resource}: {ev.observation}")

    print("\n" + "-" * 70)
    print("RECOMMENDED REMEDIATION & POLICY GOVERNANCE")
    print("-" * 70)
    print(f"Action:            {report.recommended_action}")
    print(f"Recommendation:    {report.recommended_remediation}")
    print(f"Risk Level:        {report.risk_level}")
    print(f"Policy Decision:   {report.policy_decision}")
    if report.policy_reason:
        print(f"Policy Reason:     {report.policy_reason}")
    if report.approval_id:
        print(f"Approval ID:       {report.approval_id}")
    print("=" * 70 + "\n")

    if report.status == "PENDING_APPROVAL" and (args.auto or args.yes):
        operator = args.operator or "local-sre"
        print(f"⚡ Auto-approval requested. Authorizing remediation with operator '{operator}'...")
        summary = workflow.approve_and_execute(
            approval_id=report.approval_id,
            operator_name=operator,
            reason="Auto-authorized via agentops incident --auto",
        )
        if args.json:
            print(summary.model_dump_json(indent=2))
            return
        _print_execution_summary(summary)

    elif report.status == "PENDING_APPROVAL":
        print("Remediation requires operator authorization.")
        print(f"  To authorize:  agentops approve {report.approval_id} --operator {args.operator or 'local-sre'}")
        print("  Or re-run:     agentops incident " + target + " --auto\n")


def handle_operator_approve(args):
    """
    Authorize a pending approval and execute remediation with rollout verification.
    """
    workflow = IncidentWorkflowManager()
    operator = args.operator or "local-sre"
    reason = args.reason or f"Operator '{operator}' authorized remediation via CLI"

    try:
        summary = workflow.approve_and_execute(
            approval_id=args.approval_id,
            operator_name=operator,
            reason=reason,
        )
        if args.json:
            print(summary.model_dump_json(indent=2))
            return
        _print_execution_summary(summary)
    except Exception as e:
        print(f"Error approving and executing remediation: {str(e)}", file=sys.stderr)
        sys.exit(1)


def _print_execution_summary(summary):
    print("\n" + "=" * 70)
    print("           REMEDIATION EXECUTION & POST-VERIFICATION REPORT")
    print("=" * 70)
    print(f"Execution ID:      {summary.execution_id}")
    print(f"Approval ID:       {summary.approval_id}")
    print(f"Action:            {summary.action}")
    print(f"Target:            {summary.target.get('namespace')}/{summary.target.get('resource_name')}")
    print(f"Authorization:     {summary.authorization_status}")
    print(f"Mutation Status:   {summary.mutation_status}")
    print(f"Rollout Status:    {summary.rollout_status} (Ready: {summary.ready_replicas}, Desired: {summary.desired_replicas})")
    print(f"Resolution Status: {summary.resolution_status}")
    if summary.verification_result:
        ver = summary.verification_result
        print("-" * 70)
        print("POST-VERIFICATION CHECKS")
        print(f"  Passed:          {', '.join(ver.get('checks', []))}")
        if ver.get("failed_checks"):
            print(f"  Failed:          {', '.join(ver.get('failed_checks', []))}")
        print(f"  Observations:    {ver.get('observations', {})}")
    print("=" * 70 + "\n")


def handle_serve(args):
    """
    Launch the SRE Operator Console Web UI and REST API.
    """
    app = create_app()
    host = args.host
    port = args.port
    print("\n" + "=" * 65)
    print("         AGENTOPS SRE - OPERATOR CONSOLE & REST API")
    print("=" * 65)
    print(f" Web Console UI:  http://{host}:{port}/")
    print(f" REST API:        http://{host}:{port}/api/status")
    print(f" Cluster Status:  Connected via Kubernetes context")
    print(" Press Ctrl+C to stop.")
    print("=" * 65 + "\n")
    app.run(host=host, port=port, debug=args.debug)



def handle_investigate(args):
    """
    Execute AI SRE investigation over MCP.
    """
    if args.provider == "gemini":
        llm_provider = GeminiLLMProvider(model_name=args.model or "gemini-2.5-pro")
    elif args.provider == "openai":
        llm_provider = OpenAILLMProvider(model_name=args.model or "gpt-4o")
    elif args.provider == "ollama":
        from agentops.config import settings
        llm_provider = OpenAILLMProvider(base_url=f"{settings.OLLAMA_URL}/v1", model_name=args.model or "qwen3.5:2b")
    else:
        llm_provider = MockRuleBasedLLMProvider()

    agent = SREAgent(llm_provider=llm_provider)

    logger.info(f"Starting investigation for workload '{args.workload}' in namespace '{args.namespace}' (Provider: {args.provider})")
    rca = agent.investigate(
        namespace=args.namespace,
        workload=args.workload,
        incident_description=args.incident,
    )

    if args.json:
        print(rca.model_dump_json(indent=2))
        return

    print("\n" + "=" * 70)
    print("           AGENTOPS SRE - ROOT CAUSE ANALYSIS REPORT (via MCP)")
    print("=" * 70)
    print(f"Investigation ID:  {rca.investigation_id}")
    print(f"Detected Incident: {rca.incident_type.value}")
    print(f"Severity:          {rca.severity.value}")
    print(f"Confidence:        {rca.confidence * 100:.1f}%\n")

    print("-" * 70)
    print("SUMMARY")
    print("-" * 70)
    print(rca.summary + "\n")

    print("-" * 70)
    print("ROOT CAUSE EXPLANATION")
    print("-" * 70)
    print(rca.root_cause + "\n")

    print("-" * 70)
    print(f"SUPPORTING EVIDENCE ({len(rca.evidence_ids)} items)")
    print("-" * 70)
    context_evidence = {}
    if hasattr(agent, "last_context") and agent.last_context:
        context_evidence = {ev.id: ev for ev in agent.last_context.evidence_items}

    for ev_id in rca.evidence_ids:
        if ev_id in context_evidence:
            item = context_evidence[ev_id]
            print(f"  • [{ev_id}] ({item.source.value.upper()}) {item.observation}")
        else:
            print(f"  • [{ev_id}]")

    print("\n" + "-" * 70)
    print("TIMELINE OF EVENTS")
    print("-" * 70)
    for event in rca.timeline:
        print(f"  [{event.timestamp}] ({event.source.upper()}) {event.description}")

    print("\n" + "-" * 70)
    print("RECOMMENDED REMEDIATION ACTIONS")
    print("-" * 70)
    print(rca.recommended_action)

    if rca.agent_metrics:
        print("\n" + "-" * 70)
        print("MCP & AGENT OBSERVABILITY")
        print("-" * 70)
        total_queries = (
            rca.agent_metrics.k8s_query_count
            + rca.agent_metrics.prometheus_query_count
            + rca.agent_metrics.loki_query_count
        )
        print(f"  Total Duration:     {rca.agent_metrics.duration_seconds:.2f}s")
        print(f"  Telemetry Queries:  {total_queries} (K8s: {rca.agent_metrics.k8s_query_count}, Prom: {rca.agent_metrics.prometheus_query_count}, Loki: {rca.agent_metrics.loki_query_count})")
        print(f"  LLM Latency:        {rca.agent_metrics.llm_latency_seconds:.2f}s ({rca.agent_metrics.llm_provider} / {rca.agent_metrics.llm_model})")
        if rca.agent_metrics.prompt_tokens:
            print(f"  Tokens:             Prompt: {rca.agent_metrics.prompt_tokens}, Completion: {rca.agent_metrics.completion_tokens}")
        if rca.agent_metrics.mcp_metrics:
            mcp_m = rca.agent_metrics.mcp_metrics
            invocations = mcp_m.get("tool_invocations", 0) if isinstance(mcp_m, dict) else getattr(mcp_m, "tool_invocations", 0)
            failures = mcp_m.get("tool_failures", 0) if isinstance(mcp_m, dict) else getattr(mcp_m, "tool_failures", 0)
            print(f"  MCP Invocations:    {invocations} (Failures: {failures})")

    print("=" * 70 + "\n")


def handle_mcp_server(args):
    """
    Run standalone AgentOps MCP server for external client connections.
    """
    from agentops.mcp.server import create_mcp_server

    server = create_mcp_server()
    logger.info("Starting AgentOps SRE MCP Server on stdio transport...")
    server.run()


def handle_approvals(args):
    """
    Human-in-the-loop operator approval management CLI.
    """
    manager = ApprovalManager()

    if args.approval_action == "list":
        if args.pending:
            approvals = manager.list_pending()
            print(f"\n--- PENDING APPROVAL REQUESTS ({len(approvals)}) ---")
        else:
            approvals = manager.list_all()
            print(f"\n--- ALL APPROVAL REQUESTS ({len(approvals)}) ---")

        if not approvals:
            print("No approval requests found.")
            return

        for app in approvals:
            print(f"• ID: {app.approval_id} | Status: {app.status} | Action: {app.action_request.action} | Target: {app.action_request.target.namespace}/{app.action_request.target.resource_name} | Expires: {app.expires_at}")
        print("")

    elif args.approval_action == "show":
        app = manager.get_approval(args.approval_id)
        if not app:
            print(f"Error: Approval request '{args.approval_id}' not found.", file=sys.stderr)
            sys.exit(1)

        print("\n" + "=" * 60)
        print(f"Approval Request: {app.approval_id}")
        print("=" * 60)
        print(f"Status:       {app.status}")
        print(f"Action:       {app.action_request.action}")
        print(f"Target:       {app.action_request.target.namespace}/{app.action_request.target.resource_name}")
        print(f"Risk Level:   {app.policy_decision.risk_level}")
        print(f"Reason:       {app.action_request.reason}")
        print(f"Evidence:     {', '.join(app.action_request.evidence_refs)}")
        print(f"Policies:     {', '.join(app.policy_decision.matched_policies)}")
        print(f"Requested At: {app.requested_at}")
        print(f"Expires At:   {app.expires_at}")
        if app.decided_by:
            print(f"Decided By:   {app.decided_by} ({app.decided_at})")
            print(f"Dec. Reason:  {app.decision_reason}")
        print("=" * 60 + "\n")

    elif args.approval_action == "approve":
        operator = OperatorIdentity(operator_id=args.operator, display_name=args.operator)
        try:
            res = manager.approve(args.approval_id, operator=operator, reason=args.reason)
            print(f"✓ Approval '{args.approval_id}' successfully APPROVED by '{args.operator}'.")
        except Exception as e:
            print(f"Error approving request: {str(e)}", file=sys.stderr)
            sys.exit(1)

    elif args.approval_action == "reject":
        operator = OperatorIdentity(operator_id=args.operator, display_name=args.operator)
        try:
            res = manager.reject(args.approval_id, operator=operator, reason=args.reason)
            print(f"✓ Approval '{args.approval_id}' successfully REJECTED by '{args.operator}'.")
        except Exception as e:
            print(f"Error rejecting request: {str(e)}", file=sys.stderr)
            sys.exit(1)


def handle_remediate(args):
    """
    Execute controlled Kubernetes remediation through the Security Gateway.
    """
    gateway = SecurityGateway()
    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.5.0")

    # Define granted capabilities for SRE agent in demo namespace
    caps = (
        Capability(name="k8s.remediation.restart_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"])),
        Capability(name="k8s.remediation.scale_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"], max_replicas=5)),
        Capability(name="k8s.remediation.rollback_deployment", resource="deployment", constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"])),
    )
    req_id = f"req-{uuid.uuid4().hex[:8]}"
    sec_ctx = SecurityContext(identity=identity, capabilities=caps, request_id=req_id)

    params = {}
    if args.remediation_action == "restart":
        action_name = "k8s.remediation.restart_deployment"
        reason = args.reason or "Controlled rolling restart for workload recovery"
    elif args.remediation_action == "scale":
        action_name = "k8s.remediation.scale_deployment"
        params["replicas"] = args.replicas
        reason = args.reason or f"Controlled scale out to {args.replicas} replicas"
    elif args.remediation_action == "rollback":
        action_name = "k8s.remediation.rollback_deployment"
        if args.revision:
            params["revision"] = args.revision
        reason = args.reason or "Controlled rollback to stable revision"
    else:
        print(f"Unknown remediation action: {args.remediation_action}", file=sys.stderr)
        sys.exit(1)

    target = ActionTarget(
        namespace=args.namespace,
        resource_type="deployment",
        resource_name=args.deployment,
        parameters=params,
    )
    evidence_refs = [args.evidence] if args.evidence else ["E001"]
    action_req = ActionRequest(
        request_id=req_id,
        action=action_name,
        target=target,
        reason=reason,
        evidence_refs=evidence_refs,
    )

    result = gateway.execute_remediation(
        security_context=sec_ctx,
        action_request=action_req,
        approval_id=args.approval_id,
        dry_run=args.dry_run,
    )

    if args.json:
        print(result.model_dump_json(indent=2))
        return

    print("\n" + "=" * 65)
    print("      AGENTOPS CONTROLLED REMEDIATION EXECUTION REPORT")
    print("=" * 65)
    print(f"Execution ID:  {result.execution_id}")
    print(f"Status:        {result.status}")
    print(f"Action:        {result.action}")
    print(f"Target:        {result.target.get('namespace')}/{result.target.get('resource_name')}")
    if result.approval_id:
        print(f"Approval ID:   {result.approval_id}")

    if result.pre_snapshot:
        snap = result.pre_snapshot
        print("\n--- PRE-REMEDIATION SNAPSHOT ---")
        print(f"  Desired: {snap.desired_replicas} | Ready: {snap.ready_replicas} | Available: {snap.available_replicas}")
        print(f"  Pod Count: {snap.pod_count} | Restarts: {snap.pod_restarts}")

    if result.post_verification:
        ver = result.post_verification
        print("\n--- POST-REMEDIATION VERIFICATION ---")
        print(f"  Healthy:        {ver.healthy}")
        print(f"  Passed Checks:  {', '.join(ver.checks)}")
        if ver.failed_checks:
            print(f"  Failed Checks:  {', '.join(ver.failed_checks)}")
        print(f"  Observations:   {ver.observations}")

    if result.error:
        print(f"\n[NOTICE] {result.error}")

    print("=" * 65 + "\n")


def print_single_scenario_report(res):
    print("\n" + "=" * 70)
    print(f"AGENTOPS SCENARIO EVALUATION: {res.scenario_id}")
    print("=" * 70)
    print(f"Scenario Name:   {res.scenario_name}")
    print(f"Execution Mode:  {res.mode.upper()}")
    print(f"LLM Provider:    {res.provider} ({res.model})")
    print(f"Overall Result:  {'PASSED' if res.passed else 'FAILED'}")
    print(f"Overall Score:   {res.scores.overall_score * 100:.1f}%")
    print("-" * 70)
    print("DIMENSION SCORES")
    print("-" * 70)
    print(f"  RCA Accuracy:             {res.scores.rca_accuracy * 100:.1f}%")
    print(f"  Evidence Provenance:      {res.scores.evidence_accuracy * 100:.1f}%")
    print(f"  Tool Selection:           {res.scores.tool_selection * 100:.1f}%")
    print(f"  Policy Compliance:        {res.scores.policy_compliance * 100:.1f}%")
    print(f"  Remediation Correctness:  {res.scores.remediation_correctness * 100:.1f}%")
    print(f"  Verification Correctness: {res.scores.verification_correctness * 100:.1f}%")
    print(f"  Safety Score:             {res.scores.safety * 100:.1f}%")
    print(f"  Efficiency Score:         {res.scores.efficiency * 100:.1f}%")
    print("-" * 70)
    print("SAFETY & MUTATION AUDIT")
    print("-" * 70)
    print(f"  Critical Safety Failure:  {res.critical_safety_failure}")
    print(f"  Infrastructure Mutated:   {res.infrastructure_mutated} (Count: {res.mutation_count})")
    print(f"  Unexpected Mutation:      {res.unexpected_mutation}")
    if res.failures:
        print("\nFailures / Observations:")
        for f in res.failures:
            print(f"  • {f}")
    print("=" * 70 + "\n")


def print_evaluation_summary_report(summary):
    print("\n" + "=" * 75)
    print("                 AGENTOPS SRE EVALUATION REPORT (v0.6)")
    print("=" * 75)
    print(f"Run ID:          {summary.run_id}")
    print(f"Mode:            {summary.mode.upper()}")
    print(f"Provider:        {summary.provider} ({summary.model})")
    print(f"Timestamp:       {summary.timestamp}")
    print(f"Total Scenarios: {summary.total_scenarios}")
    print(f"Passed:          {summary.passed_scenarios}")
    print(f"Failed:          {summary.failed_scenarios}")
    print(f"Overall Score:   {summary.overall_score * 100:.1f}% ({'PASSED' if summary.passed else 'FAILED'})\n")

    print("-" * 75)
    print("SCENARIO RESULTS")
    print("-" * 75)
    for r in summary.results:
        status_str = "[PASSED]" if r.passed else "[FAILED]"
        dur = r.metrics.get("duration_seconds", 0.0)
        mut = r.metrics.get("mutation_count", 0)
        print(f"• {status_str} {r.scenario_id}: {r.scenario_name}")
        print(f"    Score: {r.scores.overall_score:.3f} | Duration: {dur:.3f}s | Mutations: {mut}")
        if not r.passed:
            for fail in r.failures:
                print(f"    ↳ {fail}")

    print("\n" + "-" * 75)
    print("SAFETY & INFRASTRUCTURE MUTATION AUDIT")
    print("-" * 75)
    print(f"  Critical Safety Failures: {summary.critical_safety_failures}")
    print(f"  Total Mutations:          {summary.total_mutations}")
    print(f"  Unexpected Mutations:     {summary.unexpected_mutations}")
    safety_status = "ALL CONTROLS VERIFIED SAFE" if summary.critical_safety_failures == 0 and summary.unexpected_mutations == 0 else "SAFETY CONTROLS BREACHED"
    print(f"  Safety Status:            {safety_status}")

    if summary.regression_detected:
        print("\n" + "-" * 75)
        print("REGRESSION DETECTED AGAINST BASELINE")
        print("-" * 75)
        for d in summary.regression_details:
            print(f"  • {d}")

    print("=" * 75 + "\n")


def handle_eval(args):
    """
    Handle benchmark evaluation, baseline management, and regression quality gates.
    """
    from evaluation.engine import EvaluationEngine
    from evaluation.baseline import BaselineManager

    engine = EvaluationEngine()
    baseline_mgr = BaselineManager()

    if args.eval_action == "run":
        if args.scenario:
            res = engine.run_scenario(
                scenario_id=args.scenario,
                mode=args.mode,
                provider_name=args.provider,
                model_name=args.model,
            )
            if args.json:
                print(res.model_dump_json(indent=2))
                return

            print_single_scenario_report(res)

        elif args.all:
            summary = engine.run_all(
                mode=args.mode,
                provider_name=args.provider,
                model_name=args.model,
            )
            if args.baseline:
                is_reg, details = baseline_mgr.compare(summary, baseline_path=args.baseline)

            if args.json:
                print(summary.model_dump_json(indent=2))
                return

            print_evaluation_summary_report(summary)

        else:
            print("Error: Specify either --scenario <id> or --all", file=sys.stderr)
            sys.exit(1)

    elif args.eval_action == "baseline":
        if args.baseline_action == "save":
            summary = engine.run_all(
                mode=args.mode,
                provider_name=args.provider,
                model_name=args.model,
            )
            try:
                overwrite = getattr(args, "force", True)
                path = baseline_mgr.save_baseline(summary, filepath=args.output, overwrite=overwrite)
                print(f"\n✓ Baseline successfully saved to: {path}")
                print(f"  Overall Score: {summary.overall_score * 100:.1f}% | Total Scenarios: {summary.total_scenarios}\n")
            except Exception as e:
                print(f"Error saving baseline: {str(e)}", file=sys.stderr)
                sys.exit(1)

    elif args.eval_action == "gate":
        summary = engine.run_all(
            mode=args.mode,
            provider_name=args.provider,
            model_name=args.model,
        )
        is_reg, details = baseline_mgr.compare(summary, baseline_path=args.baseline)

        if args.json:
            print(summary.model_dump_json(indent=2))
        else:
            print_evaluation_summary_report(summary)

        # Gate logic: exit 0 if all scenarios passed AND no regression
        if summary.passed and not is_reg:
            print("✓ QUALITY GATE PASSED: All benchmark scenarios meet safety, accuracy, and regression criteria.")
            sys.exit(0)
        else:
            print("✗ QUALITY GATE FAILED: Regressions or benchmark scenario failures detected!", file=sys.stderr)
            for d in details:
                print(f"  • {d}", file=sys.stderr)
            for r in summary.results:
                if not r.passed:
                    print(f"  • Failed Scenario '{r.scenario_id}': {', '.join(r.failures)}", file=sys.stderr)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="AgentOps: Secure AI SRE Platform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 0. SRE Operator Unified Commands (v0.7)
    inc_p = subparsers.add_parser("incident", help="Unified single-command incident investigation & remediation")
    inc_p.add_argument("target", help="Target workload (e.g. demo-app or demo/demo-app)")
    inc_p.add_argument("--namespace", default="demo", help="Kubernetes namespace (defaults to target prefix or demo)")
    inc_p.add_argument("--incident", default=None, help="Incident context or alert description")
    inc_p.add_argument("--provider", choices=["mock", "gemini", "openai", "ollama"], default="mock", help="LLM Provider")
    inc_p.add_argument("--model", default=None, help="Specific LLM model name")
    inc_p.add_argument("--dry-run", action="store_true", help="Evaluate policy & risk without creating approval or executing")
    inc_p.add_argument("--auto", action="store_true", help="Non-interactive execution (auto-authorizes if approval required)")
    inc_p.add_argument("-y", "--yes", action="store_true", help="Confirm execution without interactive confirmation")
    inc_p.add_argument("--operator", default="local-sre", help="Operator identity for authorization audit")
    inc_p.add_argument("--json", action="store_true", help="Output report as raw JSON")
    inc_p.set_defaults(func=handle_operator_incident)

    single_app_p = subparsers.add_parser("approve", help="Approve and execute remediation with post-rollout verification")
    single_app_p.add_argument("approval_id", help="Pending Approval ID (e.g. appr-12345678)")
    single_app_p.add_argument("--operator", default="local-sre", help="Operator identity for authorization audit")
    single_app_p.add_argument("--reason", default=None, help="Approval justification")
    single_app_p.add_argument("--json", action="store_true", help="Output execution summary as raw JSON")
    single_app_p.set_defaults(func=handle_operator_approve)

    serve_p = subparsers.add_parser("serve", help="Launch SRE Operator Console Web UI and REST API")
    serve_p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_p.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    serve_p.set_defaults(func=handle_serve)

    ui_p = subparsers.add_parser("ui", help="Alias for 'serve' to launch SRE Web Console")
    ui_p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    ui_p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    ui_p.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    ui_p.set_defaults(func=handle_serve)

    # 1. Investigate command
    inv_parser = subparsers.add_parser("investigate", help="Run AI incident investigation")
    inv_parser.add_argument("--namespace", default="demo", help="Kubernetes namespace")
    inv_parser.add_argument("--workload", default="demo-app", help="Workload name")
    inv_parser.add_argument("--incident", default=None, help="Incident description")
    inv_parser.add_argument("--provider", choices=["mock", "gemini", "openai", "ollama"], default="mock")
    inv_parser.add_argument("--model", default=None, help="Specific LLM model name")
    inv_parser.add_argument("--json", action="store_true", help="Output RCA as raw JSON")
    inv_parser.set_defaults(func=handle_investigate)

    # 2. MCP Server command
    mcp_parser = subparsers.add_parser("mcp-server", help="Run standalone MCP investigation server")
    mcp_parser.set_defaults(func=handle_mcp_server)

    # 3. Approvals command
    appr_parser = subparsers.add_parser("approvals", help="Manage human-in-the-loop approvals")
    appr_sub = appr_parser.add_subparsers(dest="approval_action", required=True)

    # list
    list_p = appr_sub.add_parser("list", help="List approval requests")
    list_p.add_argument("--pending", action="store_true", help="Show only pending approvals")

    # show
    show_p = appr_sub.add_parser("show", help="Show approval request details")
    show_p.add_argument("approval_id", help="Approval ID (e.g. appr-12345678)")

    # approve
    app_p = appr_sub.add_parser("approve", help="Approve an action request")
    app_p.add_argument("approval_id", help="Approval ID")
    app_p.add_argument("--operator", required=True, help="Operator identifier (e.g. alice.sre)")
    app_p.add_argument("--reason", default=None, help="Approval justification")

    # reject
    rej_p = appr_sub.add_parser("reject", help="Reject an action request")
    rej_p.add_argument("approval_id", help="Approval ID")
    rej_p.add_argument("--operator", required=True, help="Operator identifier")
    rej_p.add_argument("--reason", default=None, help="Rejection justification")

    appr_parser.set_defaults(func=handle_approvals)

    # 4. Remediate command
    rem_parser = subparsers.add_parser("remediate", help="Execute controlled Kubernetes remediation")
    rem_sub = rem_parser.add_subparsers(dest="remediation_action", required=True)

    # restart
    rst_p = rem_sub.add_parser("restart", help="Restart deployment")
    rst_p.add_argument("--namespace", default="demo", help="Kubernetes namespace")
    rst_p.add_argument("--deployment", default="demo-app", help="Deployment name")
    rst_p.add_argument("--reason", default=None, help="Remediation rationale")
    rst_p.add_argument("--evidence", default="E001", help="Supporting evidence ID")
    rst_p.add_argument("--approval-id", default=None, help="Approved Approval ID")
    rst_p.add_argument("--dry-run", action="store_true", help="Perform validation dry-run without mutating cluster")
    rst_p.add_argument("--json", action="store_true", help="Output raw JSON")

    # scale
    scl_p = rem_sub.add_parser("scale", help="Scale deployment replicas")
    scl_p.add_argument("--namespace", default="demo", help="Kubernetes namespace")
    scl_p.add_argument("--deployment", default="demo-app", help="Deployment name")
    scl_p.add_argument("--replicas", type=int, required=True, help="Desired replica count (1-10)")
    scl_p.add_argument("--reason", default=None, help="Remediation rationale")
    scl_p.add_argument("--evidence", default="E001", help="Supporting evidence ID")
    scl_p.add_argument("--approval-id", default=None, help="Approved Approval ID")
    scl_p.add_argument("--dry-run", action="store_true", help="Perform validation dry-run without mutating cluster")
    scl_p.add_argument("--json", action="store_true", help="Output raw JSON")

    # rollback
    rbk_p = rem_sub.add_parser("rollback", help="Rollback deployment revision")
    rbk_p.add_argument("--namespace", default="demo", help="Kubernetes namespace")
    rbk_p.add_argument("--deployment", default="demo-app", help="Deployment name")
    rbk_p.add_argument("--revision", type=int, default=None, help="Specific revision number")
    rbk_p.add_argument("--reason", default=None, help="Remediation rationale")
    rbk_p.add_argument("--evidence", default="E001", help="Supporting evidence ID")
    rbk_p.add_argument("--approval-id", default=None, help="Approved Approval ID")
    rbk_p.add_argument("--dry-run", action="store_true", help="Perform validation dry-run without mutating cluster")
    rbk_p.add_argument("--json", action="store_true", help="Output raw JSON")

    rem_parser.set_defaults(func=handle_remediate)

    # 5. Eval command (v0.6)
    eval_parser = subparsers.add_parser("eval", help="Agent Evaluation, Benchmarks & Regression Framework")
    eval_sub = eval_parser.add_subparsers(dest="eval_action", required=True)

    # eval run
    eval_run_p = eval_sub.add_parser("run", help="Run benchmark evaluation scenario(s)")
    eval_run_p.add_argument("--scenario", default=None, help="Scenario ID to evaluate (e.g. crashloop-001)")
    eval_run_p.add_argument("--all", action="store_true", help="Run all benchmark scenarios")
    eval_run_p.add_argument("--mode", choices=["replay", "live"], default="replay", help="Execution mode (replay or live)")
    eval_run_p.add_argument("--provider", choices=["mock", "gemini", "openai"], default="mock", help="LLM Provider")
    eval_run_p.add_argument("--model", default=None, help="Specific LLM model name")
    eval_run_p.add_argument("--baseline", default=None, help="Compare results against baseline JSON")
    eval_run_p.add_argument("--json", action="store_true", help="Output results as raw JSON")

    # eval baseline
    eval_base_p = eval_sub.add_parser("baseline", help="Manage evaluation baselines")
    eval_base_sub = eval_base_p.add_subparsers(dest="baseline_action", required=True)

    base_save_p = eval_base_sub.add_parser("save", help="Run evaluation and save as baseline")
    base_save_p.add_argument("--output", default=None, help="Custom baseline output JSON file path")
    base_save_p.add_argument("--mode", choices=["replay", "live"], default="replay", help="Execution mode")
    base_save_p.add_argument("--provider", choices=["mock", "gemini", "openai"], default="mock", help="LLM Provider")
    base_save_p.add_argument("--model", default=None, help="Specific LLM model name")
    base_save_p.add_argument("--force", action="store_true", default=True, help="Overwrite existing baseline file (default: True)")
    base_save_p.add_argument("--no-force", dest="force", action="store_false", help="Fail if baseline file already exists")

    # eval gate
    eval_gate_p = eval_sub.add_parser("gate", help="CI Quality Gate evaluation (exit 0 on pass, non-zero on failure)")
    eval_gate_p.add_argument("--mode", choices=["replay", "live"], default="replay", help="Execution mode")
    eval_gate_p.add_argument("--provider", choices=["mock", "gemini", "openai"], default="mock", help="LLM Provider")
    eval_gate_p.add_argument("--model", default=None, help="Specific LLM model name")
    eval_gate_p.add_argument("--baseline", default=None, help="Baseline JSON file path")
    eval_gate_p.add_argument("--json", action="store_true", help="Output results as raw JSON")

    eval_parser.set_defaults(func=handle_eval)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
