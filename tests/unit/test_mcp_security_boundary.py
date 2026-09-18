import pytest
from agentops.mcp.server import create_mcp_server


def test_mcp_server_exposes_only_authorized_tools():
    server = create_mcp_server()
    # In FastMCP/MCPServer, tools are stored in _tool_manager._tools
    tools = getattr(server, "_tool_manager", {})._tools

    registered_tool_names = set(tools.keys())

    expected_authorized_tools = {
        # Read-Only Investigation Tools
        "k8s_get_pod_health",
        "k8s_get_deployment_health",
        "k8s_get_events",
        "prom_query_error_rate",
        "prom_query_latency",
        "prom_query_memory",
        "loki_search_errors",
        "loki_search_by_request_id",
        # Controlled Remediation Tools (v0.5)
        "k8s_restart_deployment",
        "k8s_scale_deployment",
        "k8s_rollback_deployment",
    }

    assert registered_tool_names == expected_authorized_tools, (
        f"Mismatch in registered MCP tools. Extra: {registered_tool_names - expected_authorized_tools}, "
        f"Missing: {expected_authorized_tools - registered_tool_names}"
    )


def test_mcp_server_has_no_generic_mutation_tools():
    server = create_mcp_server()
    tools = getattr(server, "_tool_manager", {})._tools
    registered_tool_names = set(tools.keys())

    prohibited_tool_keywords = [
        "delete",
        "exec",
        "shell",
        "apply",
        "raw_patch",
        "edit",
        "drain",
        "cordon",
        "secret",
    ]

    for tool_name in registered_tool_names:
        for keyword in prohibited_tool_keywords:
            assert keyword not in tool_name.lower(), (
                f"Prohibited mutation tool '{tool_name}' detected on MCP Server"
            )


def test_no_arbitrary_query_tools_exposed():
    server = create_mcp_server()
    tools = getattr(server, "_tool_manager", {})._tools
    registered_tool_names = set(tools.keys())

    prohibited_raw_queries = [
        "promql_query",
        "raw_promql",
        "logql_query",
        "raw_logql",
        "run_command",
        "shell_exec",
        "kubectl_exec",
    ]

    for raw_tool in prohibited_raw_queries:
        assert raw_tool not in registered_tool_names, (
            f"Unsafe raw query tool '{raw_tool}' must NOT be exposed to LLM agents"
        )
