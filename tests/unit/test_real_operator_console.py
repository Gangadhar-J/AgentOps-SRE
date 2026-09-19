import json
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from agentops.api.app import create_app
from agentops.incident.orchestrator import IncidentWorkflowManager
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
def test_app(temp_db):
    store = SQLiteApprovalStore(db_path=temp_db)
    appr_mgr = ApprovalManager(storage=store)
    policy_engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=policy_engine, approval_manager=appr_mgr)
    workflow = IncidentWorkflowManager(gateway=gateway, approval_manager=appr_mgr)

    app = create_app(workflow_manager=workflow)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(test_app):
    return test_app.test_client()


def test_cluster_namespaces_endpoint(client):
    with patch("agentops.clients.kubernetes.KubernetesInvestigationClient.get_namespaces", return_value=["demo", "kube-system", "monitoring", "payments"]):
        res = client.get("/api/cluster/namespaces")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert "payments" in data["namespaces"]
        assert data["count"] == 4


def test_cluster_workloads_endpoint(client):
    mock_deployments = [
        {"name": "payment-api", "desired_replicas": 3, "ready_replicas": 3},
        {"name": "payment-worker", "desired_replicas": 2, "ready_replicas": 2},
    ]
    with patch("agentops.clients.kubernetes.KubernetesInvestigationClient.get_deployments", return_value=mock_deployments):
        res = client.get("/api/cluster/workloads?namespace=payments")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert data["namespace"] == "payments"
        assert "payment-api" in data["workloads"]
        assert "payment-worker" in data["workloads"]
        assert data["count"] == 2


def test_telemetry_pulse_healthy(client):
    mock_dep = {"found": True, "desired_replicas": 2, "ready_replicas": 2}
    mock_pods = [
        {"pod_name": "app-pod-1", "is_ready": True, "restart_count": 0, "current_state_reason": "Running"},
        {"pod_name": "app-pod-2", "is_ready": True, "restart_count": 0, "current_state_reason": "Running"},
    ]
    with patch("agentops.clients.kubernetes.KubernetesInvestigationClient.get_deployment_summary", return_value=mock_dep), \
         patch("agentops.clients.kubernetes.KubernetesInvestigationClient.get_pod_health_summaries", return_value=mock_pods), \
         patch("agentops.clients.kubernetes.KubernetesInvestigationClient.get_warning_events", return_value=[]), \
         patch("agentops.clients.prometheus.PrometheusClient.is_available", return_value=True), \
         patch("agentops.clients.prometheus.PrometheusClient.get_http_error_rate", return_value=0.05), \
         patch("agentops.clients.prometheus.PrometheusClient.get_http_latency_p95", return_value=0.012), \
         patch("agentops.clients.prometheus.PrometheusClient.get_memory_usage", return_value={"max_memory_mb": 64.5}):

        res = client.get("/api/telemetry/pulse?namespace=demo&workload=demo-app")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert data["pulse_status"] == "healthy"
        assert data["k8s"]["ready_pods"] == 2
        assert data["k8s"]["desired_replicas"] == 2
        assert data["prometheus"]["error_rate_pct"] == 0.05
        assert "deep_links" in data
        assert "prometheus" in data["deep_links"]
        assert "grafana" in data["deep_links"]


def test_telemetry_pulse_critical_on_crashloop(client):
    mock_dep = {"found": True, "desired_replicas": 1, "ready_replicas": 0}
    mock_pods = [
        {"pod_name": "app-pod-1", "is_ready": False, "restart_count": 5, "current_state_reason": "CrashLoopBackOff"},
    ]
    with patch("agentops.clients.kubernetes.KubernetesInvestigationClient.get_deployment_summary", return_value=mock_dep), \
         patch("agentops.clients.kubernetes.KubernetesInvestigationClient.get_pod_health_summaries", return_value=mock_pods), \
         patch("agentops.clients.kubernetes.KubernetesInvestigationClient.get_warning_events", return_value=[]), \
         patch("agentops.clients.prometheus.PrometheusClient.is_available", return_value=False):

        res = client.get("/api/telemetry/pulse?namespace=demo&workload=demo-app")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert data["pulse_status"] == "critical"
        assert any("CrashLoopBackOff" in r for r in data["reasons"])


def test_llm_models_discovery_with_ollama(client):
    mock_ollama_resp = MagicMock()
    mock_ollama_resp.status_code = 200
    mock_ollama_resp.json.return_value = {
        "models": [
            {
                "name": "qwen3.5:2b",
                "model": "qwen3.5:2b",
                "size": 1500000000,
                "details": {"parameter_size": "2B", "quantization_level": "Q4_K_M", "family": "qwen2"},
            },
            {
                "name": "granite4.1:3b",
                "model": "granite4.1:3b",
                "size": 2100000000,
                "details": {"parameter_size": "3B", "quantization_level": "Q4_K_M", "family": "granite"},
            },
        ]
    }

    with patch("requests.get", return_value=mock_ollama_resp):
        res = client.get("/api/llm/models")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert data["ollama"]["available"] is True
        assert len(data["ollama"]["models"]) == 2
        assert data["default"]["provider"] == "ollama"
        assert data["default"]["model"] == "qwen3.5:2b"
        assert data["mock"]["available"] is True


def test_demo_mode_isolation_blocks_non_demo_workloads(client):
    """
    Mode B Sandbox Isolation Invariant:
    Chaos trigger MUST reject any target that is not demo/demo-app.
    """
    # 1. Target other namespace
    res1 = client.post("/api/demo/trigger", json={
        "scenario": "crashloop",
        "namespace": "production",
        "workload": "payment-service",
    })
    assert res1.status_code == 400
    assert "strictly restricted to namespace 'demo'" in res1.get_json()["error"]

    # 2. Target other workload in demo namespace
    res2 = client.post("/api/demo/trigger", json={
        "scenario": "crashloop",
        "namespace": "demo",
        "workload": "critical-database",
    })
    assert res2.status_code == 400
    assert "strictly restricted to namespace 'demo'" in res2.get_json()["error"]


def test_investigate_preserves_source_and_runtime_metadata(client):
    """
    Verify investigation tracks source (MANUAL vs DEMO) and includes LLM runtime metadata.
    """
    res = client.post("/api/incidents/investigate", json={
        "namespace": "demo",
        "workload": "demo-app",
        "provider": "mock",
        "dry_run": True,
        "source": "MANUAL",
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["source"] == "MANUAL"
    assert "llm_runtime" in data
    if data["llm_runtime"]:
        assert data["llm_runtime"]["mode"] == "rule-engine"
        assert data["llm_runtime"]["provider"] == "mock"
