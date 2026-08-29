import pytest
from pydantic import ValidationError
from agentops.models.rca import (
    IncidentSeverity,
    IncidentType,
    RootCauseAnalysis,
    TimelineEvent,
)


def test_valid_rca_schema():
    rca = RootCauseAnalysis(
        investigation_id="inv-12345",
        incident_type=IncidentType.HIGH_ERROR_RATE,
        severity=IncidentSeverity.HIGH,
        summary="High error rate on orders endpoint",
        root_cause="Database pool connection timeout",
        confidence=0.92,
        evidence_ids=["E001", "E002"],
        timeline=[
            TimelineEvent(timestamp="2026-08-29T12:00:00Z", source="loki", description="DB Timeout")
        ],
        recommended_action="Increase connection pool size",
        requires_human_approval=True,
    )
    assert rca.incident_type == IncidentType.HIGH_ERROR_RATE
    assert rca.confidence == 0.92
    assert rca.requires_human_approval is True
    assert rca.evidence_ids == ["E001", "E002"]


def test_rca_schema_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        RootCauseAnalysis(
            investigation_id="inv-12345",
            incident_type=IncidentType.HIGH_ERROR_RATE,
            severity=IncidentSeverity.HIGH,
            summary="High error rate",
            root_cause="Database pool timeout",
            confidence=1.5,  # Invalid: must be <= 1.0
            evidence_ids=["E001"],
            recommended_action="Scale up",
            requires_human_approval=True,
        )
