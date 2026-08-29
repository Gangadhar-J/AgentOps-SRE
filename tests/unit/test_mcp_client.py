import pytest
from agentops.mcp.client import SREMCPClient
from agentops.mcp.metrics import MCPMetricsTracker


def test_mcp_client_tool_discovery():
    client = SREMCPClient()
    tools = client.discover_tools()
    assert len(tools) == 8
    names = [t["name"] for t in tools]
    assert "k8s_get_pod_health" in names
    assert "prom_query_error_rate" in names
    assert "loki_search_errors" in names


def test_mcp_client_metrics_recording():
    metrics = MCPMetricsTracker()
    client = SREMCPClient(metrics_tracker=metrics)

    # Call a valid tool
    client.call_tool("prom_query_error_rate", {"app": "demo-app", "namespace": "demo"})
    summary = metrics.summary()

    assert summary["total_requests"] == 1
    assert summary["tool_invocations"] == 1
    assert summary["tool_failures"] == 0
    assert len(summary["recent_invocations"]) == 1
    assert summary["recent_invocations"][0]["tool_name"] == "prom_query_error_rate"


def test_mcp_client_handles_unknown_tool():
    client = SREMCPClient()
    with pytest.raises(Exception):
        client.call_tool("non_existent_tool", {})

    assert client.metrics.tool_failures == 1
