import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple
from agentops.mcp.client import SREMCPClient
from agentops.models.evidence import (
    EvidenceType,
    InvestigationContext,
    TelemetrySource,
    TelemetryStatus,
)

from agentops.observability.tracing import start_span

logger = logging.getLogger("agentops.orchestrator")


class InvestigationOrchestrator:
    """
    Coordinates multi-signal evidence collection by invoking standardized tools
    STRICTLY through the Model Context Protocol (MCP) Client interface.
    """

    def __init__(self, mcp_client: Optional[SREMCPClient] = None):
        self.mcp_client = mcp_client or SREMCPClient()

    def collect_evidence(self, namespace: str, workload: str) -> Tuple[InvestigationContext, Dict[str, int]]:
        """
        Execute deterministic multi-signal evidence collection strictly via MCP.
        """
        with start_span("agent.mcp", attributes={"kubernetes.namespace": namespace, "kubernetes.workload": workload}):
            return self._collect_evidence_internal(namespace, workload)

    def _collect_evidence_internal(self, namespace: str, workload: str) -> Tuple[InvestigationContext, Dict[str, int]]:
        inv_id = f"inv-{uuid.uuid4().hex[:8]}"
        context = InvestigationContext(
            investigation_id=inv_id,
            namespace=namespace,
            workload=workload,
        )
        query_counts = {"k8s": 0, "prometheus": 0, "loki": 0}

        # Step 0: Discover available MCP tools dynamically
        try:
            discovered = self.mcp_client.discover_tools()
            logger.info(f"Discovered {len(discovered)} investigation tools on MCP server")
        except Exception as e:
            logger.warning(f"MCP tool discovery warning: {str(e)}")

        # -------------------------------------------------------------
        # 1. Kubernetes Investigation via MCP
        # -------------------------------------------------------------
        try:
            # 1a. Call k8s_get_pod_health
            pod_summaries = self.mcp_client.call_tool(
                "k8s_get_pod_health",
                {"namespace": namespace, "app": workload},
            )
            query_counts["k8s"] += 1
            context.telemetry_status["kubernetes"] = TelemetryStatus(
                source=TelemetrySource.KUBERNETES,
                available=True,
            )

            if isinstance(pod_summaries, list):
                for pod in pod_summaries:
                    pod_name = pod.get("pod_name", "unknown")
                    restarts = pod.get("restart_count", 0)
                    phase = pod.get("phase")
                    is_ready = pod.get("is_ready")
                    last_term_reason = pod.get("last_termination_reason")
                    last_exit_code = pod.get("last_exit_code")

                    obs_parts = [f"Pod '{pod_name}' phase: {phase}, ready: {is_ready}, restartCount: {restarts}"]
                    severity = "INFO"

                    if restarts > 0 or not is_ready or phase != "Running":
                        severity = "WARN"

                    if last_term_reason:
                        obs_parts.append(f"last termination reason: {last_term_reason} (exit code {last_exit_code})")
                        if last_term_reason in ("OOMKilled", "Error") or (last_exit_code and last_exit_code != 0):
                            severity = "CRITICAL"

                    context.add_evidence(
                        source=TelemetrySource.KUBERNETES,
                        resource=f"{namespace}/{pod_name}",
                        metric_or_query="mcp://k8s_get_pod_health",
                        observation=", ".join(obs_parts),
                        evidence_type=EvidenceType.FACT,
                        severity=severity,
                        raw_payload=pod,
                    )

            # 1b. Call k8s_get_events
            events = self.mcp_client.call_tool(
                "k8s_get_events",
                {"namespace": namespace, "limit": 20, "resource_name": workload},
            )
            query_counts["k8s"] += 1
            if isinstance(events, list):
                for event in events:
                    reason = event.get("reason", "")
                    if reason in ("BackOff", "OOMKilled", "Unhealthy", "Failed", "Killing"):
                        context.add_evidence(
                            source=TelemetrySource.KUBERNETES,
                            resource=f"{namespace}/{event.get('object_name', workload)}",
                            metric_or_query="mcp://k8s_get_events",
                            observation=f"Event {reason} (count {event.get('count', 1)}): {event.get('message')}",
                            evidence_type=EvidenceType.FACT,
                            severity="WARN" if reason != "OOMKilled" else "CRITICAL",
                            raw_payload=event,
                        )

        except Exception as e:
            logger.error(f"Kubernetes MCP investigation failed: {str(e)}")
            context.telemetry_status["kubernetes"] = TelemetryStatus(
                source=TelemetrySource.KUBERNETES,
                available=False,
                error_message=str(e),
            )
            context.add_evidence(
                source=TelemetrySource.KUBERNETES,
                resource=f"{namespace}/{workload}",
                metric_or_query="mcp://k8s_get_pod_health",
                observation="Kubernetes API was unreachable or unavailable during MCP investigation.",
                evidence_type=EvidenceType.FACT,
                severity="WARN",
            )

        # -------------------------------------------------------------
        # 2. Prometheus Investigation via MCP
        # -------------------------------------------------------------
        try:
            # 2a. Call prom_query_error_rate
            err_data = self.mcp_client.call_tool(
                "prom_query_error_rate",
                {"app": workload, "namespace": namespace, "duration": "2m"},
            )
            query_counts["prometheus"] += 1
            context.telemetry_status["prometheus"] = TelemetryStatus(
                source=TelemetrySource.PROMETHEUS,
                available=True,
            )

            error_rate = err_data.get("error_rate_percentage") if isinstance(err_data, dict) else None
            if error_rate is not None:
                severity = "CRITICAL" if error_rate > 30 else ("WARN" if error_rate > 5 else "INFO")
                context.add_evidence(
                    source=TelemetrySource.PROMETHEUS,
                    resource=workload,
                    metric_or_query="mcp://prom_query_error_rate",
                    observation=f"HTTP 5xx error rate is currently {error_rate}% over the last 2m window.",
                    evidence_type=EvidenceType.FACT,
                    severity=severity,
                )

            # 2b. Call prom_query_memory (real telemetry)
            mem_data = self.mcp_client.call_tool(
                "prom_query_memory",
                {"app": workload, "namespace": namespace},
            )
            query_counts["prometheus"] += 1
            max_mem_mb = mem_data.get("max_memory_mb") if isinstance(mem_data, dict) else None
            metric_name = mem_data.get("metric_name", "process_resident_memory_bytes") if isinstance(mem_data, dict) else "memory"
            if max_mem_mb is not None and max_mem_mb > 0:
                severity = "CRITICAL" if max_mem_mb > 80 else ("WARN" if max_mem_mb > 35 else "INFO")
                context.add_evidence(
                    source=TelemetrySource.PROMETHEUS,
                    resource=workload,
                    metric_or_query="mcp://prom_query_memory",
                    observation=f"Prometheus memory metric '{metric_name}' reported {max_mem_mb} MB active memory usage across workload pods.",
                    evidence_type=EvidenceType.FACT,
                    severity=severity,
                    raw_payload=mem_data,
                )

        except Exception as e:
            logger.error(f"Prometheus MCP investigation failed: {str(e)}")
            context.telemetry_status["prometheus"] = TelemetryStatus(
                source=TelemetrySource.PROMETHEUS,
                available=False,
                error_message=str(e),
            )
            context.add_evidence(
                source=TelemetrySource.PROMETHEUS,
                resource=workload,
                metric_or_query="mcp://prom_query_error_rate",
                observation="Prometheus server was unreachable or unavailable during MCP investigation.",
                evidence_type=EvidenceType.FACT,
                severity="WARN",
            )

        # -------------------------------------------------------------
        # 3. Loki Investigation via MCP
        # -------------------------------------------------------------
        try:
            # 3a. Call loki_search_errors
            logs = self.mcp_client.call_tool(
                "loki_search_errors",
                {"namespace": namespace, "app": workload, "lookback_seconds": 90, "limit": 20},
            )
            query_counts["loki"] += 1
            context.telemetry_status["loki"] = TelemetryStatus(
                source=TelemetrySource.LOKI,
                available=True,
            )

            if isinstance(logs, list):
                for log in logs:
                    msg = log.get("message") or log.get("raw", "")
                    err_type = log.get("error_type", "Error")
                    req_id = log.get("request_id")
                    severity = "ERROR"
                    if "FATAL" in msg or "panic" in msg.lower() or err_type == "FatalProcessCrash":
                        severity = "CRITICAL"
                        obs = f"Fatal crash log captured: {msg}"
                    elif "memory" in msg.lower() and "leak" in msg.lower():
                        severity = "WARN"
                        obs = f"Memory leak warning log: {msg}"
                    else:
                        obs = f"Application error log [{err_type}]: {msg}"
                        if req_id:
                            obs += f" (request_id={req_id})"

                    context.add_evidence(
                        source=TelemetrySource.LOKI,
                        resource=f"{namespace}/{workload}",
                        metric_or_query="mcp://loki_search_errors",
                        observation=obs,
                        evidence_type=EvidenceType.FACT,
                        severity=severity,
                        raw_payload=log,
                    )

        except Exception as e:
            logger.error(f"Loki MCP investigation failed: {str(e)}")
            context.telemetry_status["loki"] = TelemetryStatus(
                source=TelemetrySource.LOKI,
                available=False,
                error_message=str(e),
            )
            context.add_evidence(
                source=TelemetrySource.LOKI,
                resource=workload,
                metric_or_query="mcp://loki_search_errors",
                observation="Loki log aggregation engine was unreachable or unavailable during MCP investigation.",
                evidence_type=EvidenceType.FACT,
                severity="WARN",
            )

        context.telemetry_status["kubernetes"].query_count = query_counts["k8s"]
        context.telemetry_status["prometheus"].query_count = query_counts["prometheus"]
        context.telemetry_status["loki"].query_count = query_counts["loki"]

        return context, query_counts
