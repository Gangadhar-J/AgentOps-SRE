import argparse
import json
import sys
from agentops.agent.investigator import SREAgent
from agentops.llm.factory import get_llm_provider

# ANSI Colors
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"


def print_banner():
    print(f"{BLUE}{BOLD}================================================================{NC}")
    print(f"{BLUE}{BOLD}         AgentOps-SRE: AI Incident Investigation Agent          {NC}")
    print(f"{BLUE}{BOLD}================================================================{NC}")


def render_rca_report(rca):
    print(f"\n{BOLD}Investigation ID:{NC}       {CYAN}{rca.investigation_id}{NC}")
    
    # Severity Color
    sev_color = RED if rca.severity.value in ("CRITICAL", "HIGH") else (YELLOW if rca.severity.value == "MEDIUM" else GREEN)
    print(f"{BOLD}Detected Incident:{NC}     {RED}{BOLD}{rca.incident_type.value}{NC}")
    print(f"{BOLD}Severity:{NC}              {sev_color}{rca.severity.value}{NC}")
    print(f"{BOLD}Confidence Score:{NC}      {GREEN}{rca.confidence * 100:.1f}%{NC}")
    print(f"{BOLD}Requires Approval:{NC}     {YELLOW}{rca.requires_human_approval}{NC} (Read-only enforcement)")
    
    print(f"\n{BOLD}Executive Summary:{NC}")
    print(f"  {rca.summary}")

    print(f"\n{BOLD}Root Cause Analysis:{NC}")
    print(f"  {rca.root_cause}")

    print(f"\n{BOLD}Supporting Evidence Items:{NC}")
    for eid in rca.evidence_ids:
        print(f"  • {CYAN}{eid}{NC}")

    if rca.timeline:
        print(f"\n{BOLD}Incident Timeline:{NC}")
        for ev in rca.timeline:
            print(f"  [{ev.timestamp[:19]}] ({ev.source}) {ev.description}")

    print(f"\n{BOLD}Recommended Remediation Action (Human-in-the-Loop):{NC}")
    for line in rca.recommended_action.split("\n"):
        print(f"  {line}")

    if rca.agent_metrics:
        m = rca.agent_metrics
        print(f"\n{BLUE}{BOLD}--- Agent Self-Observability ---{NC}")
        print(f"  Execution Duration: {m.duration_seconds}s (LLM Latency: {m.llm_latency_seconds}s)")
        print(f"  Telemetry Queries:  K8s={m.k8s_query_count}, Prometheus={m.prometheus_query_count}, Loki={m.loki_query_count}")
        print(f"  LLM Provider:       {m.llm_provider} (Model: {m.llm_model})")
        print(f"  Telemetry Status:   {m.telemetry_availability}")

    print(f"\n{BLUE}{BOLD}================================================================{NC}")


def main():
    parser = argparse.ArgumentParser(description="AgentOps SRE Incident Investigation CLI")
    subparsers = parser.add_subparsers(dest="command")

    investigate_parser = subparsers.add_parser("investigate", help="Investigate a workload incident")
    investigate_parser.add_argument("--namespace", "-n", default="demo", help="Kubernetes namespace")
    investigate_parser.add_argument("--workload", "-w", default="demo-app", help="Workload / app label name")
    investigate_parser.add_argument("--provider", "-p", default=None, help="LLM provider override (mock, gemini, openai)")
    investigate_parser.add_argument("--json", action="store_true", help="Output raw JSON format")

    args = parser.parse_args()

    if args.command == "investigate":
        if not args.json:
            print_banner()
            print(f"Starting investigation for workload '{args.workload}' in namespace '{args.namespace}'...")

        provider = get_llm_provider(args.provider)
        agent = SREAgent(llm_provider=provider)
        rca = agent.investigate(namespace=args.namespace, workload=args.workload)

        if args.json:
            print(rca.model_dump_json(indent=2))
        else:
            render_rca_report(rca)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
