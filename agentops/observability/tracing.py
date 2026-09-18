from contextlib import contextmanager
import logging
import os
import re
from typing import Any, Dict, Iterator, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from agentops.config import settings

logger = logging.getLogger("agentops.observability")

# Secret redaction patterns for span attributes
SECRET_KEY_PATTERN = re.compile(r"(key|token|secret|password|bearer|auth)", re.IGNORECASE)

_TRACER_PROVIDER: Optional[TracerProvider] = None


def sanitize_attributes(attributes: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sanitize attributes before setting on OpenTelemetry span.
    Redacts any sensitive values based on key names or token-like shapes.
    """
    if not attributes:
        return {}

    sanitized = {}
    for k, v in attributes.items():
        if SECRET_KEY_PATTERN.search(k):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, str) and (v.startswith("Bearer ") or len(v) > 50 and any(c in v for c in ("AIza", "sk-"))):
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


def init_tracer_provider() -> TracerProvider:
    """
    Initialize standard OpenTelemetry TracerProvider.
    Uses OTLP exporter if OTEL_EXPORTER_OTLP_ENDPOINT is specified,
    otherwise uses ConsoleSpanExporter (or in-memory if quiet).
    """
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        return _TRACER_PROVIDER

    resource = Resource.create({
        "service.name": "agentops-sre",
        "service.version": "0.6.0",
        "deployment.environment": "local",
    })

    provider = TracerProvider(resource=resource)

    if settings.OTEL_ENABLED:
        otlp_endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
        if otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
                provider.add_span_processor(SimpleSpanProcessor(exporter))
                logger.info(f"OpenTelemetry initialized with OTLP exporter to {otlp_endpoint}")
            except Exception as e:
                logger.warning(f"Could not initialize OTLP exporter ({str(e)}), falling back to console.")
                provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        else:
            # Console exporter for local development if OTEL_CONSOLE_EXPORT is set,
            # otherwise a lightweight in-memory or silent processor
            console_export = os.getenv("OTEL_CONSOLE_EXPORT", "false").lower() in ("1", "true", "yes")
            if console_export:
                provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            else:
                # Still process spans so tracer methods succeed without spamming stdout
                from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
                provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))

    trace.set_tracer_provider(provider)
    _TRACER_PROVIDER = provider
    return provider


def get_tracer(name: str = "agentops") -> trace.Tracer:
    """Get or initialize named OpenTelemetry tracer."""
    provider = init_tracer_provider()
    return provider.get_tracer(name)


@contextmanager
def start_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    tracer_name: str = "agentops",
) -> Iterator[trace.Span]:
    """
    Safe context manager to create a sanitized OpenTelemetry span.
    """
    tracer = get_tracer(tracer_name)
    sanitized = sanitize_attributes(attributes)
    with tracer.start_as_current_span(name, attributes=sanitized) as span:
        yield span


@contextmanager
def trace_investigation(
    investigation_id: str,
    namespace: str,
    workload: str,
    run_id: Optional[str] = None,
) -> Iterator[trace.Span]:
    """Root trace span for SRE Agent investigation lifecycle."""
    attrs = {
        "investigation.id": investigation_id,
        "kubernetes.namespace": namespace,
        "kubernetes.workload": workload,
    }
    if run_id:
        attrs["run.id"] = run_id
    with start_span("agent.investigation", attributes=attrs) as span:
        yield span


@contextmanager
def trace_mcp_tool(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Iterator[trace.Span]:
    """Child span for an individual MCP tool invocation."""
    attrs = {
        "mcp.tool.name": tool_name,
        "mcp.tool.arguments": str(arguments) if arguments else "{}",
    }
    with start_span(f"agent.mcp.{tool_name}", attributes=attrs) as span:
        yield span


@contextmanager
def trace_remediation(
    action: str,
    namespace: str,
    resource: str,
    approval_id: Optional[str] = None,
) -> Iterator[trace.Span]:
    """Span for controlled remediation execution."""
    attrs = {
        "remediation.action": action,
        "kubernetes.namespace": namespace,
        "kubernetes.resource": resource,
    }
    if approval_id:
        attrs["approval.id"] = approval_id
    with start_span("agent.remediation", attributes=attrs) as span:
        yield span


@contextmanager
def trace_approval(
    action: str,
    approval_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Iterator[trace.Span]:
    """Span for human-in-the-loop approval workflow and revalidation."""
    attrs = {
        "approval.action": action,
    }
    if approval_id:
        attrs["approval.id"] = approval_id
    if status:
        attrs["approval.status"] = status
    with start_span("agent.approval", attributes=attrs) as span:
        yield span


@contextmanager
def trace_evaluation(
    scenario_id: str,
    mode: str,
    run_id: Optional[str] = None,
) -> Iterator[trace.Span]:
    """Root span for benchmark scenario evaluation execution."""
    attrs = {
        "evaluation.scenario_id": scenario_id,
        "evaluation.mode": mode,
    }
    if run_id:
        attrs["evaluation.run_id"] = run_id
    with start_span("agent.evaluation", attributes=attrs) as span:
        yield span
