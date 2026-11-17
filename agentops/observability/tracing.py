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
        "service.version": "0.8.1",
        "deployment.environment": os.getenv("ENVIRONMENT", "local"),
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


def parse_traceparent(traceparent: str) -> Optional[Dict[str, str]]:
    """
    Parse a W3C traceparent string: 00-{trace_id}-{span_id}-{trace_flags}.
    Returns a dict with version, trace_id, span_id, trace_flags or None if invalid.
    """
    if not traceparent or not isinstance(traceparent, str):
        return None
    parts = traceparent.strip().split("-")
    if len(parts) != 4:
        return None
    version, trace_id, span_id, trace_flags = parts
    if len(version) != 2 or len(trace_id) != 32 or len(span_id) != 16 or len(trace_flags) != 2:
        return None
    try:
        int(version, 16)
        int(trace_id, 16)
        int(span_id, 16)
        int(trace_flags, 16)
    except ValueError:
        return None
    return {
        "version": version,
        "trace_id": trace_id.lower(),
        "span_id": span_id.lower(),
        "trace_flags": trace_flags.lower(),
    }


def make_traceparent(
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    sampled: bool = True,
) -> str:
    """
    Generate or format a valid W3C traceparent header string.
    Ensures 32-hex trace_id, 16-hex span_id, and valid trace_flags.
    """
    import secrets
    if trace_id:
        clean_tid = trace_id.strip().lower()
        if len(clean_tid) < 32:
            clean_tid = clean_tid.zfill(32)
        elif len(clean_tid) > 32:
            clean_tid = clean_tid[:32]
        try:
            int(clean_tid, 16)
        except ValueError:
            clean_tid = secrets.token_hex(16)
    else:
        clean_tid = secrets.token_hex(16)

    if span_id:
        clean_sid = span_id.strip().lower()
        if len(clean_sid) < 16:
            clean_sid = clean_sid.zfill(16)
        elif len(clean_sid) > 16:
            clean_sid = clean_sid[:16]
        try:
            int(clean_sid, 16)
        except ValueError:
            clean_sid = secrets.token_hex(8)
    else:
        clean_sid = secrets.token_hex(8)

    flags = "01" if sampled else "00"
    return f"00-{clean_tid}-{clean_sid}-{flags}"


@contextmanager
def use_trace_context(traceparent: Optional[str] = None, tracestate: Optional[str] = None) -> Iterator[Optional[Any]]:
    """
    Context manager to attach a W3C trace context across boundaries (e.g. background worker threads).
    Spans started within this context will automatically be linked as child spans with the same trace ID.
    """
    if not traceparent:
        yield None
        return

    from opentelemetry.context import attach, detach
    carrier = {"traceparent": traceparent}
    if tracestate:
        carrier["tracestate"] = tracestate

    ctx = extract_trace_context(carrier)
    token = attach(ctx)
    try:
        yield ctx
    finally:
        detach(token)


def inject_trace_context(carrier: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Inject W3C trace context into a dictionary carrier (traceparent, tracestate).
    """
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    carrier_dict = carrier if carrier is not None else {}
    TraceContextTextMapPropagator().inject(carrier_dict)
    return carrier_dict


def extract_trace_context(carrier: Dict[str, str]) -> Any:
    """
    Extract W3C trace context from carrier dictionary.
    """
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    return TraceContextTextMapPropagator().extract(carrier)


def get_current_trace_id() -> Optional[str]:
    """
    Return active OpenTelemetry trace ID as 32-character hex string if active.
    """
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().trace_id, "032x")
    return None
