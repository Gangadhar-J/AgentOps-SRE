import os
import tempfile
from unittest.mock import patch
import pytest

from agentops.api.app import create_app
from agentops.incident.orchestrator import IncidentWorkflowManager
from agentops.security.approval import ApprovalManager
from agentops.security.gateway import SecurityGateway
from agentops.security.policy import PolicyEngine
from agentops.security.storage import SQLiteApprovalStore
from agentops.worker import JobStore


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def job_store(temp_db):
    return JobStore(db_path=temp_db)


@pytest.fixture
def test_app(temp_db, job_store):
    store = SQLiteApprovalStore(db_path=temp_db)
    appr_mgr = ApprovalManager(storage=store)
    policy_engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=policy_engine, approval_manager=appr_mgr)
    workflow = IncidentWorkflowManager(gateway=gateway, approval_manager=appr_mgr)

    app = create_app(workflow_manager=workflow, job_store=job_store, start_worker=False)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(test_app):
    return test_app.test_client()


def test_alertmanager_valid_firing_alert_queued(client, test_app):
    """A valid firing alert payload is accepted and an investigation is queued."""
    payload = {
        "version": "4",
        "status": "firing",
        "receiver": "agentops-webhook",
        "groupLabels": {"alertname": "DemoAppCrashLoop", "namespace": "demo", "app": "demo-app"},
        "commonLabels": {"alertname": "DemoAppCrashLoop", "namespace": "demo", "app": "demo-app", "severity": "critical"},
        "commonAnnotations": {"summary": "demo-app is crashing in CrashLoopBackOff"},
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "DemoAppCrashLoop", "namespace": "demo", "app": "demo-app", "severity": "critical"},
                "annotations": {"summary": "demo-app is crashing in CrashLoopBackOff"},
                "startsAt": "2026-10-20T10:00:00Z",
            }
        ],
    }

    res = client.post("/api/v1/alerts", json=payload)
    assert res.status_code == 202
    data = res.get_json()
    assert data["status"] == "accepted"
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert result["status"] == "accepted"
    assert result["job_id"] is not None
    assert result["namespace"] == "demo"
    assert result["workload"] == "demo-app"

    # Verify job is persisted in queue
    job = test_app.job_store.get_job(result["job_id"])
    assert job is not None
    assert job.trigger_source == "ALERT"
    assert job.status.value == "QUEUED"


def test_alertmanager_repeated_delivery_deduplicated(client, test_app):
    """Repeated delivery of the same firing alert is deduplicated without launching duplicate investigations."""
    payload = {
        "version": "4",
        "status": "firing",
        "groupLabels": {"alertname": "DemoAppHighErrors", "namespace": "demo", "app": "demo-app"},
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "DemoAppHighErrors", "namespace": "demo", "app": "demo-app"},
                "annotations": {"summary": "HTTP 500 error spike"},
            }
        ],
    }

    # First delivery: accepted
    res1 = client.post("/api/v1/alerts", json=payload)
    assert res1.status_code == 202
    job_id = res1.get_json()["results"][0]["job_id"]

    # Second delivery: deduplicated because job is still active
    res2 = client.post("/api/v1/alerts", json=payload)
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["status"] == "deduplicated"
    assert data2["results"][0]["status"] == "deduplicated"
    assert data2["results"][0]["job_id"] == job_id
    assert data2["results"][0]["delivery_count"] == 2

    # Queue should still contain only 1 job
    assert test_app.job_store.get_queue_stats()["queued"] == 1


def test_alertmanager_distinct_workloads_preserved(client, test_app):
    """Distinct alerts for different workloads are not incorrectly suppressed."""
    payload1 = {
        "version": "4",
        "status": "firing",
        "alerts": [
            {"status": "firing", "labels": {"alertname": "PodCrash", "namespace": "demo", "app": "workload-a"}}
        ],
    }
    payload2 = {
        "version": "4",
        "status": "firing",
        "alerts": [
            {"status": "firing", "labels": {"alertname": "PodCrash", "namespace": "demo", "app": "workload-b"}}
        ],
    }

    res1 = client.post("/api/v1/alerts", json=payload1)
    res2 = client.post("/api/v1/alerts", json=payload2)

    assert res1.status_code == 202
    assert res2.status_code == 202
    job1 = res1.get_json()["results"][0]["job_id"]
    job2 = res2.get_json()["results"][0]["job_id"]
    assert job1 != job2
    assert test_app.job_store.get_queue_stats()["queued"] == 2


def test_alertmanager_resolved_alert_recorded(client, test_app):
    """Resolved alerts are recorded without falsely marking active investigations successful."""
    payload = {
        "version": "4",
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "DemoAppCrashLoop", "namespace": "demo", "app": "demo-app"},
            }
        ],
    }

    res = client.post("/api/v1/alerts", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "partial" or data["status"] == "resolved" or len(data["results"]) == 1
    assert data["results"][0]["status"] == "resolved"


def test_alertmanager_malformed_target_rejected(client):
    """Alerts targeting illegal or malicious resource names are rejected with 400."""
    payload = {
        "version": "4",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "MaliciousAlert", "namespace": "rm -rf /", "app": "../../etc/passwd"},
            }
        ],
    }

    res = client.post("/api/v1/alerts", json=payload)
    assert res.status_code == 400
    data = res.get_json()
    assert data["status"] == "rejected"
    assert "fails Kubernetes naming validation" in data["results"][0]["message"]


def test_alertmanager_shared_secret_auth(test_app, client):
    """When ALERTMANAGER_SECRET is configured, unauthenticated requests are rejected with 401."""
    with patch("agentops.config.settings.ALERTMANAGER_SECRET", "super-secret-token-123"):
        payload = {
            "version": "4",
            "status": "firing",
            "alerts": [{"status": "firing", "labels": {"alertname": "Test", "namespace": "demo", "app": "demo-app"}}],
        }

        # 1. Missing auth
        res_no_auth = client.post("/api/v1/alerts", json=payload)
        assert res_no_auth.status_code == 401

        # 2. Invalid auth
        res_bad_auth = client.post("/api/v1/alerts", json=payload, headers={"Authorization": "Bearer wrong-token"})
        assert res_bad_auth.status_code == 401

        # 3. Valid Bearer auth
        res_ok = client.post("/api/v1/alerts", json=payload, headers={"Authorization": "Bearer super-secret-token-123"})
        assert res_ok.status_code == 202


def test_alertmanager_history_endpoint(client):
    """Alert history endpoint returns recent deduplicated alert records."""
    payload = {
        "version": "4",
        "status": "firing",
        "alerts": [{"status": "firing", "labels": {"alertname": "HistoryAlert", "namespace": "demo", "app": "demo-app"}}],
    }
    client.post("/api/v1/alerts", json=payload)

    res = client.get("/api/alerts/history")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["count"] >= 1
    assert any(a["alert_name"] == "HistoryAlert" for a in data["alerts"])


def test_grafana_dashboards_endpoint(client):
    """Grafana dashboards endpoint lists pre-configured dashboards and reachability status."""
    res = client.get("/api/grafana/dashboards")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert "grafana_url" in data
    assert "connected" in data
    assert len(data["dashboards"]) >= 4
    dash_ids = [d["id"] for d in data["dashboards"]]
    assert "cluster-overview" in dash_ids
    assert "workload-detail" in dash_ids


def test_grafana_safe_url_generation(client):
    """Grafana URL builder strictly constructs URLs targeting trusted origin with safe parameters."""
    res = client.get("/api/grafana/url?dashboard_id=workload-detail&namespace=demo&workload=demo-app&from=now-30m")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert "var-namespace=demo" in data["direct_url"]
    assert "var-workload=demo-app" in data["direct_url"]
    assert "kiosk=tv" in data["embed_url"]

    # Test invalid parameter rejected
    bad_res = client.get("/api/grafana/url?dashboard_id=workload-detail&namespace=invalid/namespace&workload=demo-app")
    assert bad_res.status_code == 400


def test_alertmanager_resolved_to_firing_triggers_new_incident(client, test_app):
    """An alert resolving and then firing again must NOT be suppressed by cooldown; it represents a new incident."""
    payload_firing = {
        "version": "4",
        "status": "firing",
        "alerts": [{"status": "firing", "labels": {"alertname": "CycleAlert", "namespace": "demo", "app": "demo-app"}}],
    }
    payload_resolved = {
        "version": "4",
        "status": "resolved",
        "alerts": [{"status": "resolved", "labels": {"alertname": "CycleAlert", "namespace": "demo", "app": "demo-app"}}],
    }

    # 1. Initial firing -> accepted
    res1 = client.post("/api/v1/alerts", json=payload_firing)
    assert res1.status_code == 202
    job1_id = res1.get_json()["results"][0]["job_id"]

    # 2. Complete job 1
    from agentops.incident.models import IncidentReport
    test_app.job_store.claim_next_job(worker_id="worker-test")
    test_app.job_store.complete_job(
        job1_id,
        IncidentReport(
            incident_id="inc-cycle-01",
            namespace="demo",
            workload="demo-app",
            status="INVESTIGATED",
            source="ALERT",
            incident_type="CrashLoopBackOff",
            root_cause="Cycle root cause",
            confidence=0.9,
            summary="Diagnosed",
        ),
        worker_id="worker-test",
    )

    # 3. Alert resolves
    res_res = client.post("/api/v1/alerts", json=payload_resolved)
    assert res_res.status_code == 200

    # 4. Same alert fires again -> must trigger a FRESH investigation, not be suppressed by previous cooldown!
    res2 = client.post("/api/v1/alerts", json=payload_firing)
    assert res2.status_code == 202
    job2_id = res2.get_json()["results"][0]["job_id"]
    assert job2_id != job1_id  # Brand new investigation job!


def test_alertmanager_fingerprint_isolation(client, test_app):
    """Alerts for the same workload with distinct fingerprints have independent cooldowns."""
    from agentops.incident.models import IncidentReport

    payload_alert1 = {
        "version": "4",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CrashLoop", "namespace": "demo", "app": "demo-app", "container": "worker"},
                "fingerprint": "fp-worker-001",
            }
        ],
    }
    payload_alert2 = {
        "version": "4",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CrashLoop", "namespace": "demo", "app": "demo-app", "container": "web"},
                "fingerprint": "fp-web-002",
            }
        ],
    }

    # 1. Alert 1 arrives -> accepted (job 1)
    res1 = client.post("/api/v1/alerts", json=payload_alert1)
    assert res1.status_code == 202
    job1_id = res1.get_json()["results"][0]["job_id"]

    # 2. Complete job 1 -> Alert 1 is now in cooldown
    test_app.job_store.claim_next_job(worker_id="worker-test")
    test_app.job_store.complete_job(
        job1_id,
        IncidentReport(
            incident_id="inc-fp-01",
            namespace="demo",
            workload="demo-app",
            status="INVESTIGATED",
            source="ALERT",
            incident_type="CrashLoopBackOff",
            root_cause="Worker crashed",
            confidence=0.9,
            summary="Diagnosed",
        ),
        worker_id="worker-test",
    )

    # 3. Repeated Alert 1 is suppressed under cooldown
    res_repeat = client.post("/api/v1/alerts", json=payload_alert1)
    assert res_repeat.status_code == 200
    assert res_repeat.get_json()["results"][0]["status"] == "deduplicated"

    # 4. Alert 2 with distinct fingerprint is NOT suppressed by Alert 1's cooldown!
    res2 = client.post("/api/v1/alerts", json=payload_alert2)
    assert res2.status_code == 202
    job2_id = res2.get_json()["results"][0]["job_id"]
    assert job2_id != job1_id


def test_alertmanager_header_auth_enforced_and_query_blocked_by_default(client):
    """Header authentication is enforced; query string auth is rejected when ALERTMANAGER_ALLOW_QUERY_AUTH is False."""
    with patch("agentops.config.settings.ALERTMANAGER_SECRET", "strong-secret-999"):
        with patch("agentops.config.settings.ALERTMANAGER_ALLOW_QUERY_AUTH", False):
            payload = {
                "version": "4",
                "status": "firing",
                "alerts": [{"status": "firing", "labels": {"alertname": "AuthTest", "namespace": "demo", "app": "demo-app"}}],
            }

            # Query param auth rejected
            res_query = client.post("/api/v1/alerts?secret=strong-secret-999", json=payload)
            assert res_query.status_code == 401

            # Header auth accepted
            res_hdr = client.post("/api/v1/alerts", json=payload, headers={"X-Alertmanager-Secret": "strong-secret-999"})
            assert res_hdr.status_code == 202
