from datetime import datetime, timezone
import os
import tempfile
from unittest.mock import patch
import pytest

from agentops.api.app import create_app
from agentops.incident.orchestrator import IncidentWorkflowManager
from agentops.models.remediation import RemediationResult, RemediationVerification
from agentops.security.approval import ApprovalManager
from agentops.security.storage import SQLiteApprovalStore
from agentops.security.gateway import SecurityGateway
from agentops.security.policy import PolicyEngine
from agentops.worker import JobStore


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def test_app(temp_db, mock_orchestrator):
    store = SQLiteApprovalStore(db_path=temp_db)
    job_store = JobStore(db_path=temp_db)
    appr_mgr = ApprovalManager(storage=store)
    policy_engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=policy_engine, approval_manager=appr_mgr)
    workflow = IncidentWorkflowManager(gateway=gateway, approval_manager=appr_mgr, orchestrator=mock_orchestrator)

    app = create_app(workflow_manager=workflow, job_store=job_store, start_worker=False)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(test_app):
    return test_app.test_client()


def test_index_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"AgentOps SRE" in res.data
    assert b"Operator Console" in res.data


def test_get_status_endpoint(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["version"].startswith("0.8")
    assert "cluster" in data
    assert "components" in data
    assert "pending_approvals" in data


def test_investigate_endpoint(test_app, client):
    res = client.post(
        "/api/incidents/investigate",
        json={"namespace": "demo", "workload": "demo-app", "provider": "mock", "dry_run": True},
    )
    assert res.status_code == 202
    data = res.get_json()
    assert data["status"] == "accepted"
    assert data["job_status"] == "QUEUED"
    assert data["workload"] == "demo-app"

    # Worker claims and completes the job
    assert test_app.worker.run_once() is True

    # Retrieve terminal result
    res_result = client.get(f"/api/investigations/{data['job_id']}/result")
    assert res_result.status_code == 200
    res_data = res_result.get_json()
    assert res_data["workload"] == "demo-app"
    assert res_data["status"] == "DRY_RUN_EVALUATED"
    assert res_data["policy_decision"] == "REQUIRE_APPROVAL"


def test_active_incident_endpoint(test_app, client):
    # Before investigation
    res1 = client.get("/api/incidents/active")
    assert res1.status_code == 200
    assert res1.get_json()["active_incident"] is None

    # After investigation
    inv_res = client.post(
        "/api/incidents/investigate",
        json={"namespace": "demo", "workload": "demo-app", "provider": "mock", "dry_run": False},
    )
    assert inv_res.status_code == 202
    test_app.worker.run_once()

    res2 = client.get("/api/incidents/active")
    assert res2.status_code == 200
    data = res2.get_json()
    assert data["workload"] == "demo-app"
    assert data["approval_id"] is not None


def test_approval_lifecycle_via_api(test_app, client):
    # 1. Investigate to generate pending approval
    inv_res = client.post(
        "/api/incidents/investigate",
        json={"namespace": "demo", "workload": "demo-app", "provider": "mock", "dry_run": False},
    )
    assert inv_res.status_code == 202
    test_app.worker.run_once()

    active_res = client.get("/api/incidents/active")
    app_id = active_res.get_json()["approval_id"]
    assert app_id is not None

    # 2. List pending approvals
    list_res = client.get("/api/approvals")
    assert list_res.status_code == 200
    apps = list_res.get_json()["approvals"]
    assert any(a["approval_id"] == app_id for a in apps)

    # 3. Approve via API
    now_str = datetime.now(timezone.utc).isoformat()
    mock_rem_result = RemediationResult(
        execution_id="exec-api-123",
        request_id="req-api-123",
        action="k8s.remediation.restart_deployment",
        target={"namespace": "demo", "resource_type": "deployment", "resource_name": "demo-app"},
        status="SUCCESS",
        approval_id=app_id,
        started_at=now_str,
        completed_at=now_str,
        post_verification=RemediationVerification(
            healthy=True,
            checks=["pod_readiness"],
            failed_checks=[],
            observations={"ready_replicas": 1, "expected_replicas": 1},
        ),
    )

    with patch("agentops.security.gateway.SecurityGateway.execute_remediation", return_value=mock_rem_result):
        appr_res = client.post(
            f"/api/approvals/{app_id}/approve",
            json={"operator": "alice.sre", "reason": "Verified RCA via web console"},
        )
        assert appr_res.status_code == 200
        summary = appr_res.get_json()
        assert summary["resolution_status"] == "RESOLVED"
        assert summary["mutation_status"] == "SUCCESS"


def test_rejection_via_api(test_app, client):
    inv_res = client.post(
        "/api/incidents/investigate",
        json={"namespace": "demo", "workload": "demo-app", "provider": "mock", "dry_run": False},
    )
    assert inv_res.status_code == 202
    test_app.worker.run_once()

    active_res = client.get("/api/incidents/active")
    app_id = active_res.get_json()["approval_id"]
    assert app_id is not None

    rej_res = client.post(
        f"/api/approvals/{app_id}/reject",
        json={"operator": "alice.sre", "reason": "Not approved"},
    )
    assert rej_res.status_code == 200
    data = rej_res.get_json()
    assert data["status"] == "REJECTED"


def test_demo_trigger_invalid_scenario_blocked(client):
    res = client.post("/api/demo/trigger", json={"scenario": "rm -rf /"})
    assert res.status_code == 400
    assert "Invalid or missing scenario" in res.get_json()["error"]


def test_eval_summary_endpoint(client):
    res = client.get("/api/eval/summary")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["overall_score"] is not None
    assert data["passing"] is True
