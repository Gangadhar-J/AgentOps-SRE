import json
import logging
import os
import sys
import pytest

# Add demo-app directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "demo-app")))
from app import app, JsonFormatter


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "demo-order-service"
    assert "pod" in data
    assert "namespace" in data


def test_ready_endpoint_healthy(client):
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ready"


def test_order_creation_success(client):
    payload = {"item": "turbo-engine", "amount": 2}
    response = client.post("/orders", json=payload)
    assert response.status_code == 201
    data = response.get_json()
    assert "order_id" in data
    assert data["item"] == "turbo-engine"
    assert data["amount"] == 2
    assert "processed_by_pod" in data


def test_order_list(client):
    client.post("/orders", json={"item": "gear", "amount": 5})
    response = client.get("/orders")
    assert response.status_code == 200
    data = response.get_json()
    assert "total" in data
    assert "orders" in data
    assert data["total"] >= 1


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    content = response.data.decode("utf-8")
    assert "http_requests_total" in content
    assert "http_request_duration_seconds" in content


def test_json_formatter():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="demo-app",
        level=logging.INFO,
        pathname="app.py",
        lineno=50,
        msg="Test structured log message",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-12345"
    record.endpoint = "/orders"
    record.status_code = 200

    formatted = formatter.format(record)
    log_data = json.loads(formatted)

    assert log_data["level"] == "INFO"
    assert log_data["service"] == "demo-order-service"
    assert log_data["request_id"] == "req-12345"
    assert log_data["endpoint"] == "/orders"
    assert log_data["status_code"] == 200
    assert log_data["message"] == "Test structured log message"
