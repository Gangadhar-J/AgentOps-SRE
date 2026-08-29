from unittest.mock import MagicMock, patch
import pytest
from agentops.clients.prometheus import PrometheusClient
from agentops.clients.loki import LokiClient


@patch("requests.get")
def test_prometheus_client_query_instant(mock_get):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"app": "demo-app", "status": "500"},
                    "value": [1787980000, "15"],
                }
            ],
        },
    }
    mock_get.return_value = mock_res

    client = PrometheusClient(base_url="http://localhost:9090")
    data = client.query_instant('http_requests_total{status="500"}')
    assert "result" in data
    assert data["result"][0]["metric"]["status"] == "500"


@patch("requests.get")
def test_loki_client_query_range_parses_json_lines(mock_get):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "status": "success",
        "data": {
            "result": [
                {
                    "stream": {"app": "demo-app", "namespace": "demo"},
                    "values": [
                        [
                            "1787980000000000000",
                            '{"timestamp": "2026-08-29T12:00:00Z", "level": "ERROR", "message": "Connection refused", "error_type": "DatabaseConnectionTimeout", "request_id": "req-999"}',
                        ]
                    ],
                }
            ]
        },
    }
    mock_get.return_value = mock_res

    client = LokiClient(base_url="http://localhost:3100")
    logs = client.query_range('{namespace="demo"}')
    assert len(logs) == 1
    assert logs[0]["error_type"] == "DatabaseConnectionTimeout"
    assert logs[0]["request_id"] == "req-999"
    assert logs[0]["level"] == "ERROR"
