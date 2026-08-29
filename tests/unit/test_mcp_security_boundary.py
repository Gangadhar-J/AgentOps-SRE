import pytest
from agentops.mcp.client import SREMCPClient
from agentops.mcp.server import create_mcp_server


def test_mcp_server_exposes_only_authorized_read_only_tools():
    """
    Security Guarantee Test:
    Ensures that the MCP Server registers ONLY the 8 authorized read-only investigation tools.
    """
    client = SREMCPClient()
    discovered = client.discover_tools()
    tool_names = {t["name"] for t in discovered}

    expected_tools = {
        "k8s_get_pod_health",
        "k8s_get_deployment_health",
        "k8s_get_events",
        "prom_query_error_rate",
        "prom_query_latency",
        "prom_query_memory",
        "loki_search_errors",
        "loki_search_by_request_id",
    }

    assert tool_names == expected_tools, f"MCP tool set mismatch: {tool_names}"


def test_mcp_server_has_no_mutation_tools():
    """
    Security Guarantee Test:
    Ensures that NO mutation tools exist on the MCP Server.
    """
    client = SREMCPClient()
    discovered = client.discover_tools()
    prohibited_keywords = [
        "delete",
        "patch",
        "update",
        "scale",
        "restart",
        "exec",
        "apply",
        "create",
        "shell",
        "kill",
        "write",
    ]

    for tool in discovered:
        name = tool["name"].lower()
        for prohibited in prohibited_keywords:
            assert prohibited not in name, f"Security Violation: Prohibited mutation tool '{name}' exposed on MCP Server!"


def test_no_arbitrary_query_tools_exposed():
    """
    Security Guarantee Test:
    Ensures arbitrary query execution tools (promql_query, logql_query) are NOT exposed.
    """
    client = SREMCPClient()
    discovered = client.discover_tools()
    tool_names = [t["name"] for t in discovered]

    assert "promql_query" not in tool_names
    assert "prometheus_query" not in tool_names
    assert "logql_query" not in tool_names
    assert "loki_query" not in tool_names
    assert "shell_exec" not in tool_names
