from agentops.models.evidence import (
    EvidenceItem,
    EvidenceType,
    InvestigationContext,
    TelemetrySource,
)


def test_evidence_item_creation_and_provenance():
    item = EvidenceItem(
        id="E001",
        source=TelemetrySource.KUBERNETES,
        evidence_type=EvidenceType.FACT,
        resource="demo/demo-app-123",
        metric_or_query="kubectl get pods",
        observation="Container terminated with reason OOMKilled",
        severity="CRITICAL",
    )
    assert item.id == "E001"
    assert item.source == TelemetrySource.KUBERNETES
    assert item.evidence_type == EvidenceType.FACT
    assert item.severity == "CRITICAL"


def test_investigation_context_adds_sequential_ids():
    context = InvestigationContext(
        investigation_id="inv-test-01",
        namespace="demo",
        workload="demo-app",
    )
    e1 = context.add_evidence(
        source=TelemetrySource.PROMETHEUS,
        resource="demo-app",
        metric_or_query="http_requests_total",
        observation="HTTP 500 error rate at 48%",
    )
    e2 = context.add_evidence(
        source=TelemetrySource.LOKI,
        resource="demo/demo-app",
        metric_or_query="DatabaseConnectionTimeout",
        observation="Database connection timeout in pool",
    )

    assert e1.id == "E001"
    assert e2.id == "E002"
    assert len(context.evidence_items) == 2
