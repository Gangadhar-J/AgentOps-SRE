from agentops.llm.mock_provider import MockRuleBasedLLMProvider
from agentops.models.evidence import (
    EvidenceType,
    InvestigationContext,
    TelemetrySource,
    TelemetryStatus,
)
from agentops.models.rca import IncidentType


def test_mock_provider_diagnoses_oomkilled():
    provider = MockRuleBasedLLMProvider()
    context = InvestigationContext(investigation_id="inv-oom", namespace="demo", workload="demo-app")
    context.telemetry_status["kubernetes"] = TelemetryStatus(source=TelemetrySource.KUBERNETES, available=True)
    context.telemetry_status["loki"] = TelemetryStatus(source=TelemetrySource.LOKI, available=True)

    context.add_evidence(
        source=TelemetrySource.KUBERNETES,
        resource="demo/demo-app-xxx",
        metric_or_query="kubectl get pods",
        observation="Container terminated with reason OOMKilled (exit code 137)",
    )
    context.add_evidence(
        source=TelemetrySource.LOKI,
        resource="demo/demo-app",
        metric_or_query="loki",
        observation="Memory allocation leak running: allocated 120 MB",
    )

    rca, meta = provider.generate_rca(context)
    assert rca.incident_type == IncidentType.RESOURCE_EXHAUSTION
    assert rca.confidence >= 0.90
    assert "E001" in rca.evidence_ids
    assert "E002" in rca.evidence_ids
    assert rca.requires_human_approval is True


def test_mock_provider_diagnoses_crashloop():
    provider = MockRuleBasedLLMProvider()
    context = InvestigationContext(investigation_id="inv-crash", namespace="demo", workload="demo-app")
    context.add_evidence(
        source=TelemetrySource.KUBERNETES,
        resource="demo/demo-app-xxx",
        metric_or_query="kubectl get pods",
        observation="Pod in CrashLoopBackOff state, exit code 1",
    )
    context.add_evidence(
        source=TelemetrySource.LOKI,
        resource="demo/demo-app",
        metric_or_query="loki",
        observation="Fatal crash log captured: FATAL: Unhandled segmentation fault",
    )

    rca, _ = provider.generate_rca(context)
    assert rca.incident_type == IncidentType.CRASHLOOP_BACKOFF
    assert rca.confidence >= 0.90
    assert "E001" in rca.evidence_ids
    assert "E002" in rca.evidence_ids


def test_mock_provider_diagnoses_high_error_rate():
    provider = MockRuleBasedLLMProvider()
    context = InvestigationContext(investigation_id="inv-err", namespace="demo", workload="demo-app")
    context.add_evidence(
        source=TelemetrySource.PROMETHEUS,
        resource="demo-app",
        metric_or_query="http_requests_total",
        observation="HTTP 5xx error rate is currently 50.0% over the last 2m window.",
    )
    context.add_evidence(
        source=TelemetrySource.LOKI,
        resource="demo/demo-app",
        metric_or_query="loki",
        observation="Application error log [DatabaseConnectionTimeout]: Connection to replica timed out",
    )

    rca, _ = provider.generate_rca(context)
    assert rca.incident_type == IncidentType.HIGH_ERROR_RATE
    assert rca.confidence >= 0.90
    assert "E001" in rca.evidence_ids
    assert "E002" in rca.evidence_ids
