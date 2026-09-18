import pytest
from agentops.mcp.client import SREMCPClient


def test_mcp_client_tool_discovery():
    client = SREMCPClient()
    tools = client.discover_tools()
    # 8 investigation tools + 3 remediation tools = 11 total tools
    assert len(tools) == 11
    tool_names = [t["name"] for t in tools]
    assert "k8s_get_pod_health" in tool_names
    assert "k8s_restart_deployment" in tool_names
    assert "prom_query_error_rate" in tool_names
    assert "loki_search_errors" in tool_names


def test_mcp_client_metrics_recording():
    client = SREMCPClient()
    # Call a known investigation tool
    try:
        client.call_tool("prom_query_error_rate", {"app": "demo-app", "namespace": "demo"})
    except Exception:
        pass

    metrics = client.metrics.summary()
    assert metrics["tool_invocations"] >= 1
    assert metrics["total_requests"] >= 1


def test_mcp_client_handles_unknown_tool():
    client = SREMCPClient()
    with pytest.raises(Exception):
        client.call_tool("non_existent_tool", {})
    metrics = client.metrics.summary()
    assert metrics["tool_failures"] >= 1
