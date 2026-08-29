import pytest
from pydantic import ValidationError
from agentops.mcp.schemas import (
    K8sGetDeploymentHealthInput,
    K8sGetEventsInput,
    K8sGetPodHealthInput,
    LokiSearchByRequestIdInput,
    LokiSearchErrorsInput,
    PromQueryErrorRateInput,
    PromQueryLatencyInput,
    PromQueryMemoryInput,
)


def test_k8s_schemas_validation():
    # Valid pod health input
    pod_inp = K8sGetPodHealthInput(namespace="demo", app="demo-app")
    assert pod_inp.namespace == "demo"
    assert pod_inp.app == "demo-app"

    # Valid deployment health input
    dep_inp = K8sGetDeploymentHealthInput(namespace="demo", deployment="demo-app")
    assert dep_inp.deployment == "demo-app"

    # Valid events input
    ev_inp = K8sGetEventsInput(namespace="demo", limit=50)
    assert ev_inp.limit == 50

    # Invalid events limit (> 100)
    with pytest.raises(ValidationError):
        K8sGetEventsInput(limit=500)


def test_prom_schemas_validation():
    # Valid error rate input
    prom_err = PromQueryErrorRateInput(app="demo-app", duration="5m")
    assert prom_err.duration == "5m"

    # Invalid duration pattern (rejects malicious injection / invalid PromQL syntax)
    with pytest.raises(ValidationError):
        PromQueryErrorRateInput(duration="invalid_window")

    # Valid latency input
    prom_lat = PromQueryLatencyInput(app="demo-app", quantile=0.99)
    assert prom_lat.quantile == 0.99

    # Invalid quantile (> 1.0)
    with pytest.raises(ValidationError):
        PromQueryLatencyInput(quantile=1.5)


def test_loki_schemas_validation():
    # Valid error search
    loki_err = LokiSearchErrorsInput(namespace="demo", app="demo-app", lookback_seconds=120)
    assert loki_err.lookback_seconds == 120

    # Valid request id search
    loki_req = LokiSearchByRequestIdInput(request_id="req-12345-abc")
    assert loki_req.request_id == "req-12345-abc"
