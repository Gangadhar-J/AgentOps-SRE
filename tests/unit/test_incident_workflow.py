from datetime import datetime, timezone
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from agentops.incident.models import EvidenceDetail, IncidentReport, RemediationExecutionSummary
from agentops.incident.orchestrator import IncidentWorkflowManager
from agentops.models.rca import IncidentSeverity, IncidentType, RootCauseAnalysis
from agentops.models.remediation import RemediationResult, RemediationVerification
from agentops.security.approval import ApprovalManager
from agentops.security.storage import SQLiteApprovalStore
from agentops.security.gateway import SecurityGateway
from agentops.security.policy import PolicyEngine


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def workflow_manager(temp_db):
    store = SQLiteApprovalStore(db_path=temp_db)
    appr_mgr = ApprovalManager(storage=store)
    policy_engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=policy_engine, approval_manager=appr_mgr)
    return IncidentWorkflowManager(gateway=gateway, approval_manager=appr_mgr)


def test_incident_models():
    detail = EvidenceDetail(
        id="E001",
        source="kubernetes",
        resource="pod/demo-app-xxx",
        metric_or_query="get_pod_health",
        observation="Pod in CrashLoopBackOff",
        severity="CRITICAL",
    )
    assert detail.source == "kubernetes"

    report = IncidentReport(
        incident_id="inc-test-01",
        namespace="demo",
        workload="demo-app",
        status="PENDING_APPROVAL",
        incident_type="CrashLoopBackOff",
        confidence=0.95,
        summary="Crashing container",
        root_cause="Fatal panic",
        evidence_summary={"kubernetes": 1, "total": 1},
        evidence_items=[detail],
        approval_required=True,
        approval_id="appr-test-1234",
    )
    assert report.incident_id == "inc-test-01"
    assert report.approval_required is True


def test_investigate_and_recommend_dry_run(workflow_manager):
    # In dry-run mode, policy is evaluated but no approval request is persisted
    report = workflow_manager.investigate_and_recommend(
        namespace="demo",
        workload="demo-app",
        provider_name="mock",
        dry_run=True,
    )
    assert report.status == "DRY_RUN_EVALUATED"
    assert report.approval_required is True
    assert report.approval_id is None
    assert report.policy_decision == "REQUIRE_APPROVAL"
    assert workflow_manager.get_active_incident() is not None


def test_investigate_and_recommend_standard(workflow_manager):
    # Standard investigation generates pending approval
    report = workflow_manager.investigate_and_recommend(
        namespace="demo",
        workload="demo-app",
        provider_name="mock",
        dry_run=False,
    )
    assert report.status == "PENDING_APPROVAL"
    assert report.approval_required is True
    assert report.approval_id is not None
    assert report.approval_id.startswith("appr-")
    assert report.recommended_action == "k8s.remediation.restart_deployment"

    # Pending approvals list includes it
    pending = workflow_manager.get_pending_approvals()
    assert len(pending) == 1
    assert pending[0]["approval_id"] == report.approval_id


def test_approve_and_execute_success(workflow_manager):
    # First generate incident and pending approval
    report = workflow_manager.investigate_and_recommend(
        namespace="demo",
        workload="demo-app",
        provider_name="mock",
    )
    approval_id = report.approval_id

    now_str = datetime.now(timezone.utc).isoformat()
    mock_rem_result = RemediationResult(
        execution_id="exec-mock-123",
        request_id="req-mock-123",
        action="k8s.remediation.restart_deployment",
        target={"namespace": "demo", "resource_type": "deployment", "resource_name": "demo-app"},
        status="SUCCESS",
        approval_id=approval_id,
        started_at=now_str,
        completed_at=now_str,
        post_verification=RemediationVerification(
            healthy=True,
            checks=["pod_readiness", "zero_restart_increase"],
            failed_checks=[],
            observations={"ready_replicas": 1, "expected_replicas": 1},
        ),
    )

    with patch.object(workflow_manager.gateway, "execute_remediation", return_value=mock_rem_result) as mock_exec:
        summary = workflow_manager.approve_and_execute(
            approval_id=approval_id,
            operator_name="sre-operator",
            reason="Confirmed restart is safe",
        )
        assert summary.resolution_status == "RESOLVED"
        assert summary.rollout_status == "HEALTHY"
        assert summary.ready_replicas == 1
        assert summary.execution_id == "exec-mock-123"
        mock_exec.assert_called_once()

        # Active incident status is updated
        assert workflow_manager.get_active_incident().status == "RESOLVED"


def test_approve_and_execute_single_use_token_replay_rejected(workflow_manager):
    report = workflow_manager.investigate_and_recommend(
        namespace="demo",
        workload="demo-app",
        provider_name="mock",
    )
    approval_id = report.approval_id

    now_str = datetime.now(timezone.utc).isoformat()
    mock_rem_result = RemediationResult(
        execution_id="exec-mock-123",
        request_id="req-mock-123",
        action="k8s.remediation.restart_deployment",
        target={"namespace": "demo", "resource_type": "deployment", "resource_name": "demo-app"},
        status="SUCCESS",
        approval_id=approval_id,
        started_at=now_str,
        completed_at=now_str,
    )

    with patch.object(workflow_manager.gateway, "execute_remediation", return_value=mock_rem_result):
        workflow_manager.approve_and_execute(approval_id=approval_id, operator_name="sre-operator")

    # Second execution attempt with same approval ID must fail
    with pytest.raises(Exception):
        workflow_manager.approve_and_execute(approval_id=approval_id, operator_name="sre-operator")


def test_reject_flow(workflow_manager):
    report = workflow_manager.investigate_and_recommend(
        namespace="demo",
        workload="demo-app",
        provider_name="mock",
    )
    approval_id = report.approval_id

    res = workflow_manager.reject(
        approval_id=approval_id,
        operator_name="sre-operator",
        reason="Manual restart preferred",
    )
    assert res["status"] == "REJECTED"
    assert res["decided_by"] == "sre-operator"
    assert workflow_manager.get_active_incident().status == "REJECTED"
    assert len(workflow_manager.get_pending_approvals()) == 0
