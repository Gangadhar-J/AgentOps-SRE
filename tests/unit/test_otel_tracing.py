from opentelemetry import trace
from agentops.observability.tracing import (
    get_tracer,
    sanitize_attributes,
    start_span,
    trace_investigation,
    trace_mcp_tool,
    trace_remediation,
)


def test_sanitize_attributes_redacts_secrets():
    raw_attrs = {
        "workload": "demo-app",
        "api_key": "AIzaSySecretTokenValue123",
        "user_token": "sk-proj-abc123456789",
        "normal_metric": 42,
        "auth_header": "Bearer secret-value-999",
    }
    sanitized = sanitize_attributes(raw_attrs)
    assert sanitized["workload"] == "demo-app"
    assert sanitized["normal_metric"] == 42
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["user_token"] == "[REDACTED]"
    assert sanitized["auth_header"] == "[REDACTED]"


def test_start_span_creates_valid_span():
    tracer = get_tracer("test-tracer")
    with start_span("test.operation", attributes={"test.key": "val"}) as span:
        assert span is not None
        assert span.is_recording() is True


def test_trace_investigation_and_child_spans():
    with trace_investigation(
        investigation_id="inv-test-123",
        namespace="demo",
        workload="demo-app",
        run_id="run-123",
    ) as root_span:
        assert root_span is not None

        # Child tool span
        with trace_mcp_tool("k8s_get_pod_health", {"namespace": "demo"}) as tool_span:
            assert tool_span is not None

        # Child remediation span
        with trace_remediation(
            action="k8s.remediation.restart_deployment",
            namespace="demo",
            resource="demo-app",
            approval_id="appr-123",
        ) as rem_span:
            assert rem_span is not None
