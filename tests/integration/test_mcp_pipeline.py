import pytest
from agentops.agent.orchestrator import InvestigationOrchestrator
from agentops.mcp.client import SREMCPClient
from agentops.models.evidence import TelemetrySource


def test_mcp_live_tools_execution():
    client = SREMCPClient()

    # 1. Test Kubernetes MCP tools
    pods = client.call_tool("k8s_get_pod_health", {"namespace": "demo", "app": "demo-app"})
    assert isinstance(pods, list)
    assert len(pods) >= 1
    assert pods[0]["namespace"] == "demo"
    assert "phase" in pods[0]

    dep = client.call_tool("k8s_get_deployment_health", {"namespace": "demo", "deployment": "demo-app"})
    assert dep["found"] is True
    assert dep["deployment"] == "demo-app"

    events = client.call_tool("k8s_get_events", {"namespace": "demo", "limit": 10})
    assert isinstance(events, list)

    # 2. Test Prometheus MCP tools (Real Telemetry)
    err = client.call_tool("prom_query_error_rate", {"app": "demo-app", "namespace": "demo"})
    assert "error_rate_percentage" in err

    lat = client.call_tool("prom_query_latency", {"app": "demo-app", "namespace": "demo"})
    assert "latency_seconds" in lat

    mem = client.call_tool("prom_query_memory", {"app": "demo-app", "namespace": "demo"})
    assert "max_memory_mb" in mem
    assert "metric_name" in mem
    assert "pods" in mem

    # 3. Test Loki MCP tools
    logs = client.call_tool("loki_search_errors", {"namespace": "demo", "app": "demo-app"})
    assert isinstance(logs, list)


def test_orchestrator_evidence_collection_via_mcp():
    orchestrator = InvestigationOrchestrator()
    context, query_counts = orchestrator.collect_evidence(namespace="demo", workload="demo-app")

    assert context.investigation_id.startswith("inv-")
    assert context.namespace == "demo"
    assert context.workload == "demo-app"
    assert len(context.evidence_items) >= 1
    assert query_counts["k8s"] >= 1
    assert query_counts["prometheus"] >= 1
    assert query_counts["loki"] >= 1

    # Verify MCP provenance URIs (proves MCP was in runtime execution path)
    mcp_queries = [e.metric_or_query for e in context.evidence_items if e.metric_or_query.startswith("mcp://")]
    assert len(mcp_queries) >= 1
