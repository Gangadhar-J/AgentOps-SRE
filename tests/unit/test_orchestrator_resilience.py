from unittest.mock import MagicMock
from agentops.agent.orchestrator import InvestigationOrchestrator
from agentops.mcp.client import SREMCPClient
from agentops.models.evidence import TelemetrySource


def test_orchestrator_handles_unavailable_prometheus_via_mcp():
    mock_client = MagicMock(spec=SREMCPClient)
    mock_client.discover_tools.return_value = [{"name": "k8s_get_pod_health"}]

    def mock_call_tool(name, args):
        if "prom" in name:
            raise ConnectionError("Prometheus connection refused")
        if "k8s" in name:
            return []
        if "loki" in name:
            return []
        return {}

    mock_client.call_tool.side_effect = mock_call_tool

    orchestrator = InvestigationOrchestrator(mcp_client=mock_client)
    context, query_counts = orchestrator.collect_evidence(namespace="demo", workload="demo-app")

    assert context.telemetry_status["prometheus"].available is False
    assert context.telemetry_status["kubernetes"].available is True
    assert context.telemetry_status["loki"].available is True

    prom_evidence = [e for e in context.evidence_items if e.source == TelemetrySource.PROMETHEUS]
    assert len(prom_evidence) == 1
    assert "unreachable or unavailable" in prom_evidence[0].observation.lower()


def test_orchestrator_handles_unavailable_loki_via_mcp():
    mock_client = MagicMock(spec=SREMCPClient)
    mock_client.discover_tools.return_value = []

    def mock_call_tool(name, args):
        if "loki" in name:
            raise ConnectionError("Loki timeout")
        return []

    mock_client.call_tool.side_effect = mock_call_tool

    orchestrator = InvestigationOrchestrator(mcp_client=mock_client)
    context, _ = orchestrator.collect_evidence(namespace="demo", workload="demo-app")

    assert context.telemetry_status["loki"].available is False
    loki_evidence = [e for e in context.evidence_items if e.source == TelemetrySource.LOKI]
    assert len(loki_evidence) == 1
    assert "unreachable or unavailable" in loki_evidence[0].observation.lower()
