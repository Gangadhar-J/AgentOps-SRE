"""
Hermetic test fixtures and in-memory test doubles for AgentOps-SRE test suite.
Ensures unit tests are deterministic, isolated, and completely decoupled from
external infrastructure (Kind, Kubernetes, Prometheus, Loki, Ollama).
"""

from typing import Any, Dict, List, Optional
import pytest

from agentops.agent.orchestrator import InvestigationOrchestrator
from agentops.mcp.metrics import MCPMetricsTracker


class MockSREMCPClient:
    """
    Hermetic in-memory test double for SREMCPClient.
    Provides deterministic telemetry responses without contacting
    Kubernetes, Prometheus, Loki, or the live MCP daemon.
    """

    def __init__(
        self,
        pod_health: Optional[List[Dict[str, Any]]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        prom_metrics: Optional[Dict[str, Any]] = None,
        loki_logs: Optional[Dict[str, Any]] = None,
    ):
        self.pod_health = pod_health if pod_health is not None else [
            {
                "pod_name": "demo-app-7d4b9c8b7f-x9w2z",
                "phase": "Running",
                "is_ready": False,
                "restart_count": 8,
                "last_termination_reason": "Error",
                "last_exit_code": 1,
            }
        ]
        self.events = events if events is not None else [
            {
                "reason": "BackOff",
                "object_name": "demo-app-7d4b9c8b7f-x9w2z",
                "count": 8,
                "message": "Back-off restarting failed container",
            }
        ]
        self.prom_metrics = prom_metrics or {"resultType": "vector", "result": []}
        self.loki_logs = loki_logs or {"data": {"result": []}}
        self.metrics = MCPMetricsTracker()

    def discover_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "k8s_get_pod_health"},
            {"name": "k8s_get_events"},
            {"name": "k8s_get_deployment_health"},
            {"name": "prom_query_instant"},
            {"name": "loki_query_range"},
            {"name": "k8s_restart_deployment"},
            {"name": "k8s_scale_deployment"},
            {"name": "k8s_rollback_deployment"},
        ]

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        self.metrics.record_tool_call(tool_name, 0.005, True)
        if "pod_health" in tool_name:
            return self.pod_health
        elif "events" in tool_name:
            return self.events
        elif "deployment" in tool_name:
            return {
                "name": arguments.get("deployment", "demo-app"),
                "desired_replicas": 1,
                "ready_replicas": 0,
                "available_replicas": 0,
                "unavailable_replicas": 1,
            }
        elif "prom" in tool_name:
            return self.prom_metrics
        elif "loki" in tool_name:
            return self.loki_logs
        return {}


@pytest.fixture
def mock_mcp_client() -> MockSREMCPClient:
    """Fixture returning an isolated MockSREMCPClient with CrashLoopBackOff symptoms."""
    return MockSREMCPClient()


@pytest.fixture
def mock_orchestrator(mock_mcp_client: MockSREMCPClient) -> InvestigationOrchestrator:
    """Fixture returning an InvestigationOrchestrator backed by the isolated test double."""
    return InvestigationOrchestrator(mcp_client=mock_mcp_client)


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """
    Automatically assign markers based on directory location:
    - tests/unit/ and tests/test_demo_app.py -> unit
    - tests/integration/ and tests/test_infrastructure.py -> integration
    - tests/scenario/ -> scenario
    """
    for item in items:
        fspath = str(item.fspath)
        if "tests/unit/" in fspath or "test_demo_app.py" in fspath:
            item.add_marker(pytest.mark.unit)
        elif "tests/integration/" in fspath or "test_infrastructure.py" in fspath:
            item.add_marker(pytest.mark.integration)
        elif "tests/scenario/" in fspath:
            item.add_marker(pytest.mark.scenario)

