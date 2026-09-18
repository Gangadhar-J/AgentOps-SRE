import logging
from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer
from agentops.agent.tools import (
    KubernetesInvestigationTools,
    LokiInvestigationTools,
    PrometheusInvestigationTools,
)
from agentops.clients.remediation import KubernetesRemediationClient

logger = logging.getLogger("agentops.mcp.server")


def create_mcp_server() -> MCPServer:
    """
    Creates and configures the AgentOps SRE MCP Server.
    Registers read-only investigation tools and controlled remediation tools.
    """
    server = MCPServer("agentops-sre-investigation-tools")

    k8s_tools = KubernetesInvestigationTools()
    prom_tools = PrometheusInvestigationTools()
    loki_tools = LokiInvestigationTools()
    k8s_remediation = KubernetesRemediationClient()

    # -------------------------------------------------------------
    # 1. Kubernetes Investigation Tools (Read-Only)
    # -------------------------------------------------------------
    @server.tool(
        name="k8s_get_pod_health",
        description="Inspect pod health, phases, restart counts, container termination reasons (e.g. OOMKilled, Error), and exit codes.",
    )
    def k8s_get_pod_health(namespace: str = "demo", app: Optional[str] = "demo-app", pod: Optional[str] = None) -> List[Dict[str, Any]]:
        return k8s_tools.get_pod_health(namespace=namespace, app=app, pod=pod)

    @server.tool(
        name="k8s_get_deployment_health",
        description="Inspect Kubernetes deployment replica statuses (desired, ready, available, unavailable) and rollout conditions.",
    )
    def k8s_get_deployment_health(namespace: str = "demo", deployment: str = "demo-app") -> Dict[str, Any]:
        return k8s_tools.get_deployment_health(namespace=namespace, deployment=deployment)

    @server.tool(
        name="k8s_get_events",
        description="Retrieve recent warning events from the Kubernetes cluster (e.g. BackOff, Unhealthy, Failed, Killing).",
    )
    def k8s_get_events(namespace: str = "demo", resource_name: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
        return k8s_tools.get_warning_events(namespace=namespace, limit=limit, resource_name=resource_name)

    # -------------------------------------------------------------
    # 2. Kubernetes Controlled Remediation Tools (Write - Gateway Authorized)
    # -------------------------------------------------------------
    @server.tool(
        name="k8s_restart_deployment",
        description="Execute a controlled rolling restart on a target deployment for crash recovery.",
    )
    def k8s_restart_deployment(namespace: str = "demo", deployment: str = "demo-app", reason: Optional[str] = None) -> Dict[str, Any]:
        return k8s_remediation.restart_deployment(namespace=namespace, deployment=deployment, reason=reason)

    @server.tool(
        name="k8s_scale_deployment",
        description="Execute controlled horizontal scaling of deployment replicas within safe bounds (1-10).",
    )
    def k8s_scale_deployment(namespace: str = "demo", deployment: str = "demo-app", replicas: int = 1) -> Dict[str, Any]:
        return k8s_remediation.scale_deployment(namespace=namespace, deployment=deployment, replicas=replicas)

    @server.tool(
        name="k8s_rollback_deployment",
        description="Roll back a target deployment to a previous or specific stable revision.",
    )
    def k8s_rollback_deployment(namespace: str = "demo", deployment: str = "demo-app", revision: Optional[int] = None) -> Dict[str, Any]:
        return k8s_remediation.rollback_deployment(namespace=namespace, deployment=deployment, revision=revision)

    # -------------------------------------------------------------
    # 3. Prometheus Investigation Tools (Real Telemetry)
    # -------------------------------------------------------------
    @server.tool(
        name="prom_query_error_rate",
        description="Query HTTP 5xx error rate percentage for a workload over a specified sliding time window.",
    )
    def prom_query_error_rate(app: str = "demo-app", namespace: str = "demo", duration: str = "2m") -> Dict[str, Any]:
        return prom_tools.query_error_rate(app=app, namespace=namespace, duration=duration)

    @server.tool(
        name="prom_query_latency",
        description="Query HTTP request latency percentiles (e.g. p95) for a workload over a specified sliding time window.",
    )
    def prom_query_latency(app: str = "demo-app", namespace: str = "demo", quantile: float = 0.95, duration: str = "5m") -> Dict[str, Any]:
        return prom_tools.query_latency(app=app, namespace=namespace, quantile=quantile, duration=duration)

    @server.tool(
        name="prom_query_memory",
        description="Query real process and container memory usage metrics (bytes, MB) from Prometheus for a target workload.",
    )
    def prom_query_memory(app: str = "demo-app", namespace: str = "demo") -> Dict[str, Any]:
        return prom_tools.query_memory(app=app, namespace=namespace)

    # -------------------------------------------------------------
    # 4. Loki Investigation Tools
    # -------------------------------------------------------------
    @server.tool(
        name="loki_search_errors",
        description="Search recent structured application error logs, fatal panics, and memory allocation warnings with stack traces.",
    )
    def loki_search_errors(namespace: str = "demo", app: str = "demo-app", lookback_seconds: int = 90, limit: int = 20) -> List[Dict[str, Any]]:
        err_logs = loki_tools.search_error_logs(namespace=namespace, app=app, lookback_seconds=lookback_seconds, limit=limit)
        fatal_logs = loki_tools.search_fatal_crashes(namespace=namespace, app=app, lookback_seconds=lookback_seconds, limit=5)
        mem_logs = loki_tools.search_memory_leaks(namespace=namespace, app=app, lookback_seconds=lookback_seconds, limit=5)
        return err_logs + fatal_logs + mem_logs

    @server.tool(
        name="loki_search_by_request_id",
        description="Search structured logs matching a specific request ID or trace ID across the lookback window.",
    )
    def loki_search_by_request_id(request_id: str, namespace: str = "demo", lookback_minutes: int = 10, limit: int = 20) -> List[Dict[str, Any]]:
        return loki_tools.search_by_request_id(request_id=request_id, namespace=namespace, lookback_minutes=lookback_minutes, limit=limit)

    return server


if __name__ == "__main__":
    server = create_mcp_server()
    server.run()
