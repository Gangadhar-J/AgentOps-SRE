import argparse
import json
import logging
import sys
from agentops.agent.investigator import SREAgent
from agentops.config import settings
from agentops.llm.gemini_provider import GeminiLLMProvider
from agentops.llm.mock_provider import MockRuleBasedLLMProvider
from agentops.llm.openai_provider import OpenAILLMProvider
from agentops.security.approval import ApprovalManager
from agentops.security.operator import OperatorIdentity

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agentops.cli")


def handle_investigate(args):
    """
    Execute AI SRE investigation over MCP.
    """
    if args.provider == "gemini":
        llm_provider = GeminiLLMProvider(model_name=args.model or "gemini-2.5-pro")
    elif args.provider == "openai":
        llm_provider = OpenAILLMProvider(model_name=args.model or "gpt-4o")
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
    for ev_id in rca.evidence_ids:
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
        print(f"  Total Duration:     {rca.agent_metrics.total_investigation_duration_seconds:.2f}s")
        print(f"  Telemetry Queries:  {rca.agent_metrics.total_telemetry_queries}")
        if rca.agent_metrics.mcp_metrics:
            mcp_m = rca.agent_metrics.mcp_metrics
            print(f"  MCP Invocations:    {mcp_m.tool_invocations} (Failures: {mcp_m.tool_failures})")
            print(f"  MCP Tool Latencies: {mcp_m.average_tool_duration_seconds:.4f}s avg")

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


def main():
    parser = argparse.ArgumentParser(description="AgentOps: Secure AI SRE Platform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Investigate command
    inv_parser = subparsers.add_parser("investigate", help="Run AI incident investigation")
    inv_parser.add_argument("--namespace", default="demo", help="Kubernetes namespace")
    inv_parser.add_argument("--workload", default="demo-app", help="Workload name")
    inv_parser.add_argument("--incident", default=None, help="Incident description")
    inv_parser.add_argument("--provider", choices=["mock", "gemini", "openai"], default="mock")
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
