import argparse
import json
from unittest.mock import MagicMock, patch
import pytest

from agentops.cli import handle_operator_approve, handle_operator_incident
from agentops.incident.models import EvidenceDetail, IncidentReport, RemediationExecutionSummary


def test_handle_operator_incident_dry_run(capsys):
    mock_report = IncidentReport(
        incident_id="inc-test-dry",
        namespace="demo",
        workload="demo-app",
        status="DRY_RUN_EVALUATED",
        incident_type="CrashLoopBackOff",
        confidence=0.98,
        summary="Application container crash looping",
        root_cause="Process exit 1 due to fatal panic",
        evidence_summary={"kubernetes": 1, "prometheus": 1, "loki": 1, "total": 3},
        evidence_items=[
            EvidenceDetail(
                id="E001",
                source="kubernetes",
                resource="pod/demo-app-1",
                metric_or_query="get_pod_health",
                observation="Pod CrashLoopBackOff",
            )
        ],
        recommended_action="k8s.remediation.restart_deployment",
        recommended_remediation="Restart deployment demo/demo-app",
        risk_level="HIGH",
        policy_decision="REQUIRE_APPROVAL",
        policy_reason="Production & demo mutations require human authorization",
        approval_required=True,
        approval_id=None,
    )

    args = argparse.Namespace(
        target="demo/demo-app",
        namespace="demo",
        incident=None,
        provider="mock",
        model=None,
        dry_run=True,
        auto=False,
        yes=False,
        operator="local-sre",
        json=False,
    )

    with patch("agentops.incident.orchestrator.IncidentWorkflowManager.investigate_and_recommend", return_value=mock_report):
        handle_operator_incident(args)

    captured = capsys.readouterr()
    assert "AGENTOPS SRE - INCIDENT INVESTIGATION REPORT" in captured.out
    assert "inc-test-dry" in captured.out
    assert "DRY_RUN_EVALUATED" in captured.out
    assert "REQUIRE_APPROVAL" in captured.out


def test_handle_operator_incident_json(capsys):
    mock_report = IncidentReport(
        incident_id="inc-json-01",
        namespace="demo",
        workload="demo-app",
        status="PENDING_APPROVAL",
        incident_type="CrashLoopBackOff",
        confidence=0.95,
        summary="Test summary",
        root_cause="Test root cause",
        evidence_summary={"kubernetes": 1, "total": 1},
        evidence_items=[],
        recommended_action="k8s.remediation.restart_deployment",
        recommended_remediation="Restart deployment demo/demo-app",
        risk_level="HIGH",
        policy_decision="REQUIRE_APPROVAL",
        approval_required=True,
        approval_id="appr-12345678",
    )

    args = argparse.Namespace(
        target="demo-app",
        namespace="demo",
        incident=None,
        provider="mock",
        model=None,
        dry_run=False,
        auto=False,
        yes=False,
        operator="local-sre",
        json=True,
    )

    with patch("agentops.incident.orchestrator.IncidentWorkflowManager.investigate_and_recommend", return_value=mock_report):
        handle_operator_incident(args)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["incident_id"] == "inc-json-01"
    assert data["approval_id"] == "appr-12345678"


def test_handle_operator_incident_auto_approve(capsys):
    mock_report = IncidentReport(
        incident_id="inc-auto-01",
        namespace="demo",
        workload="demo-app",
        status="PENDING_APPROVAL",
        incident_type="CrashLoopBackOff",
        confidence=0.95,
        summary="Test summary",
        root_cause="Test root cause",
        approval_required=True,
        approval_id="appr-auto-123",
    )
    mock_summary = RemediationExecutionSummary(
        execution_id="exec-auto-456",
        approval_id="appr-auto-123",
        action="k8s.remediation.restart_deployment",
        target={"namespace": "demo", "resource_name": "demo-app"},
        authorization_status="AUTHORIZED",
        mutation_status="SUCCESS",
        rollout_status="HEALTHY",
        ready_replicas=1,
        desired_replicas=1,
        resolution_status="RESOLVED",
    )

    args = argparse.Namespace(
        target="demo/demo-app",
        namespace="demo",
        incident=None,
        provider="mock",
        model=None,
        dry_run=False,
        auto=True,
        yes=False,
        operator="alice.sre",
        json=False,
    )

    with patch("agentops.incident.orchestrator.IncidentWorkflowManager.investigate_and_recommend", return_value=mock_report), \
         patch("agentops.incident.orchestrator.IncidentWorkflowManager.approve_and_execute", return_value=mock_summary):
        handle_operator_incident(args)

    captured = capsys.readouterr()
    assert "Auto-approval requested" in captured.out
    assert "REMEDIATION EXECUTION & POST-VERIFICATION REPORT" in captured.out
    assert "exec-auto-456" in captured.out
    assert "RESOLVED" in captured.out


def test_handle_operator_approve(capsys):
    mock_summary = RemediationExecutionSummary(
        execution_id="exec-manual-789",
        approval_id="appr-999",
        action="k8s.remediation.restart_deployment",
        target={"namespace": "demo", "resource_name": "demo-app"},
        authorization_status="AUTHORIZED",
        mutation_status="SUCCESS",
        rollout_status="HEALTHY",
        ready_replicas=1,
        desired_replicas=1,
        resolution_status="RESOLVED",
    )

    args = argparse.Namespace(
        approval_id="appr-999",
        operator="bob.sre",
        reason="Approved oncall",
        json=False,
    )

    with patch("agentops.incident.orchestrator.IncidentWorkflowManager.approve_and_execute", return_value=mock_summary):
        handle_operator_approve(args)

    captured = capsys.readouterr()
    assert "REMEDIATION EXECUTION & POST-VERIFICATION REPORT" in captured.out
    assert "exec-manual-789" in captured.out
