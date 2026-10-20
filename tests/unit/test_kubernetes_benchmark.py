import time
from unittest.mock import patch
import pytest

from agentops.clients.kubernetes import KubernetesInvestigationClient


def test_kubernetes_client_security_boundary_enforcement():
    """Verify that unauthorized mutation subcommands are blocked immediately by read-only security boundary."""
    client = KubernetesInvestigationClient()

    # Mutation commands must raise PermissionError
    for forbidden in ["delete", "create", "apply", "patch", "scale", "exec", "run"]:
        with pytest.raises(PermissionError, match="Unauthorized command rejected"):
            client._run_read_only_cmd(["kubectl", forbidden, "pod", "test-pod"])


def test_kubernetes_client_read_only_operations_benchmark():
    """
    Benchmark representative read-only Kubernetes operations and verify latency instrumentation.
    Operations benchmarked:
    - List namespaces
    - List deployments
    - List pods / health summaries
    - Read warning events
    - Retrieve deployment summary
    """
    mock_namespaces = {"items": [{"metadata": {"name": ns}} for ns in ["default", "demo", "monitoring"]]}
    mock_deployments = {
        "items": [
            {
                "metadata": {"name": "demo-app", "namespace": "demo"},
                "spec": {"replicas": 2},
                "status": {"replicas": 2, "readyReplicas": 2, "updatedReplicas": 2, "availableReplicas": 2},
            }
        ]
    }
    mock_pods = {
        "items": [
            {
                "metadata": {"name": "demo-app-1", "namespace": "demo"},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [{"ready": True, "restartCount": 0}],
                },
            }
        ]
    }
    mock_events = {"items": []}

    client = KubernetesInvestigationClient()

    def mock_run(args):
        # Return corresponding mock data based on args
        if "namespaces" in args:
            return mock_namespaces
        elif "deployments" in args or "deployment" in args:
            return mock_deployments
        elif "pods" in args:
            return mock_pods
        elif "events" in args:
            return mock_events
        return {"items": []}

    with patch.object(client, "_run_read_only_cmd", side_effect=mock_run):
        # 1. Benchmark namespaces
        t0 = time.perf_counter()
        ns_list = client.get_namespaces()
        ns_latency = time.perf_counter() - t0
        assert ns_list == ["default", "demo", "monitoring"]

        # 2. Benchmark deployments
        t0 = time.perf_counter()
        deps = client.get_deployments(namespace="demo")
        deps_latency = time.perf_counter() - t0
        assert len(deps) == 1
        assert deps[0]["name"] == "demo-app"

        # 3. Benchmark pod health summaries
        t0 = time.perf_counter()
        pods = client.get_pod_health_summaries(namespace="demo", label_selector="app=demo-app")
        pods_latency = time.perf_counter() - t0
        assert len(pods) == 1
        assert pods[0]["is_ready"] is True

        # 4. Benchmark warning events
        t0 = time.perf_counter()
        events = client.get_warning_events(namespace="demo", resource_name="demo-app")
        events_latency = time.perf_counter() - t0
        assert isinstance(events, list)

        # 5. Benchmark deployment summary
        t0 = time.perf_counter()
        dep_summary = client.get_deployment_summary(name="demo-app", namespace="demo")
        summary_latency = time.perf_counter() - t0
        assert dep_summary["found"] is True

        # Total benchmark verification
        total_latency = ns_latency + deps_latency + pods_latency + events_latency + summary_latency
        assert total_latency < 0.1  # Fast in-process dispatch with mock
