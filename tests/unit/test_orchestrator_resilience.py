from unittest.mock import MagicMock
from agentops.agent.orchestrator import InvestigationOrchestrator
from agentops.agent.tools import (
    KubernetesInvestigationTools,
    LokiInvestigationTools,
    PrometheusInvestigationTools,
)
from agentops.models.evidence import TelemetrySource


def test_orchestrator_handles_unavailable_prometheus():
    # Mock Prometheus as unavailable
    prom_tools = PrometheusInvestigationTools()
    prom_tools.client = MagicMock()
    prom_tools.client.is_available.return_value = False

    k8s_tools = KubernetesInvestigationTools()
    k8s_tools.client = MagicMock()
    k8s_tools.client.is_available.return_value = True
    k8s_tools.get_pod_health = MagicMock(return_value=[])
    k8s_tools.get_warning_events = MagicMock(return_value=[])

    loki_tools = LokiInvestigationTools()
    loki_tools.client = MagicMock()
    loki_tools.client.is_available.return_value = True
    loki_tools.search_error_logs = MagicMock(return_value=[])
    loki_tools.search_fatal_crashes = MagicMock(return_value=[])
    loki_tools.search_memory_leaks = MagicMock(return_value=[])

    orchestrator = InvestigationOrchestrator(
        k8s_tools=k8s_tools, prom_tools=prom_tools, loki_tools=loki_tools
    )

    context, _ = orchestrator.collect_evidence(namespace="demo", workload="demo-app")

    assert context.telemetry_status["prometheus"].available is False
    assert context.telemetry_status["kubernetes"].available is True
    assert context.telemetry_status["loki"].available is True

    # Verify that an explicit observation notes that Prometheus was unreachable
    prom_evidence = [e for e in context.evidence_items if e.source == TelemetrySource.PROMETHEUS]
    assert len(prom_evidence) == 1
    assert "unreachable or unavailable" in prom_evidence[0].observation.lower()
