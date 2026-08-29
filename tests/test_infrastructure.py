import subprocess
import time
import requests
import pytest

DEMO_APP_URL = "http://localhost:30080"
PROMETHEUS_URL = "http://localhost:30090"
GRAFANA_URL = "http://localhost:30300"
LOKI_URL = "http://localhost:31000"


def test_kind_cluster_running():
    result = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True, check=True)
    assert "agentops" in result.stdout


def test_namespaces_exist():
    result = subprocess.run(["kubectl", "get", "ns", "-o", "jsonpath={.items[*].metadata.name}"],
                            capture_output=True, text=True, check=True)
    namespaces = result.stdout.split()
    assert "demo" in namespaces
    assert "monitoring" in namespaces


def test_demo_app_running():
    result = subprocess.run(
        ["kubectl", "get", "deployment", "demo-app", "-n", "demo", "-o", "jsonpath={.status.readyReplicas}"],
        capture_output=True, text=True, check=True
    )
    ready_replicas = int(result.stdout.strip() or "0")
    assert ready_replicas >= 1


def test_demo_app_http_health():
    res = requests.get(f"{DEMO_APP_URL}/health", timeout=5)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["service"] == "demo-order-service"


def test_demo_app_order_flow():
    order_payload = {"item": "smart-sensor", "amount": 10}
    res = requests.post(f"{DEMO_APP_URL}/orders", json=order_payload, timeout=5)
    assert res.status_code == 201
    data = res.json()
    assert data["item"] == "smart-sensor"
    assert "X-Request-ID" in res.headers


def test_prometheus_scraping_target():
    res = requests.get(f"{PROMETHEUS_URL}/api/v1/targets", timeout=5)
    assert res.status_code == 200
    targets_data = res.json()
    assert targets_data["status"] == "success"

    active_targets = targets_data["data"]["activeTargets"]
    demo_targets = [t for t in active_targets if t.get("labels", {}).get("app") == "demo-app"]
    assert len(demo_targets) >= 1
    assert any(t["health"] == "up" for t in demo_targets)


def test_prometheus_query_metric():
    query_url = f"{PROMETHEUS_URL}/api/v1/query"
    params = {"query": 'http_requests_total{app="demo-app"}'}

    metric_found = False
    for _ in range(6):
        res = requests.get(query_url, params=params, timeout=5)
        if res.status_code == 200:
            results = res.json().get("data", {}).get("result", [])
            if len(results) > 0:
                metric_found = True
                break
        time.sleep(2)

    assert metric_found, "Expected http_requests_total metric for demo-app in Prometheus"


def test_loki_ready():
    ready = False
    for _ in range(6):
        try:
            res = requests.get(f"{LOKI_URL}/ready", timeout=5)
            if res.status_code == 200 and "ready" in res.text.lower():
                ready = True
                break
        except Exception:
            pass
        time.sleep(2)
    assert ready, "Loki did not report ready status within timeout"


def test_grafana_health_and_datasources():
    res = requests.get(f"{GRAFANA_URL}/api/health", timeout=5)
    assert res.status_code == 200
    assert res.json().get("database") == "ok"

    ds_res = requests.get(f"{GRAFANA_URL}/api/datasources", timeout=5)
    assert ds_res.status_code == 200
    ds_names = [ds["name"] for ds in ds_res.json()]
    assert "Prometheus" in ds_names
    assert "Loki" in ds_names


def test_alloy_daemonset_running():
    result = subprocess.run(
        ["kubectl", "get", "daemonset", "alloy", "-n", "monitoring", "-o", "jsonpath={.status.numberReady}"],
        capture_output=True, text=True, check=True
    )
    number_ready = int(result.stdout.strip() or "0")
    assert number_ready >= 1
