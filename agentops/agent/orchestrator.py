import logging
import uuid
from typing import Dict, Tuple
from agentops.agent.tools import (
    KubernetesInvestigationTools,
    LokiInvestigationTools,
    PrometheusInvestigationTools,
)
from agentops.models.evidence import (
    EvidenceType,
    InvestigationContext,
    TelemetrySource,
    TelemetryStatus,
)

logger = logging.getLogger("agentops.orchestrator")


class InvestigationOrchestrator:
    """
    Deterministically gathers and normalizes telemetry across Kubernetes, Prometheus, and Loki.
    """

    def __init__(
        self,
        k8s_tools: KubernetesInvestigationTools | None = None,
        prom_tools: PrometheusInvestigationTools | None = None,
        loki_tools: LokiInvestigationTools | None = None,
    ):
        self.k8s_tools = k8s_tools or KubernetesInvestigationTools()
        self.prom_tools = prom_tools or PrometheusInvestigationTools()
        self.loki_tools = loki_tools or LokiInvestigationTools()

    def collect_evidence(self, namespace: str, workload: str) -> Tuple[InvestigationContext, Dict[str, int]]:
        """
        Execute deterministic multi-signal evidence collection.
        """
        inv_id = f"inv-{uuid.uuid4().hex[:8]}"
        context = InvestigationContext(
            investigation_id=inv_id,
            namespace=namespace,
            workload=workload,
        )
        query_counts = {"k8s": 0, "prometheus": 0, "loki": 0}

        # -------------------------------------------------------------
        # 1. Kubernetes Investigation
        # -------------------------------------------------------------
        k8s_available = self.k8s_tools.client.is_available()
        context.telemetry_status["kubernetes"] = TelemetryStatus(
            source=TelemetrySource.KUBERNETES,
            available=k8s_available,
        )

        if k8s_available:
            try:
                # 1a. Inspect Pod Health Summaries
                pod_summaries = self.k8s_tools.get_pod_health(namespace=namespace, app=workload)
                query_counts["k8s"] += 1
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
                        metric_or_query="kubectl get pods",
                        observation=", ".join(obs_parts),
                        evidence_type=EvidenceType.FACT,
                        severity=severity,
                        raw_payload=pod,
                    )

                # 1b. Inspect Warning Events
                events = self.k8s_tools.get_warning_events(namespace=namespace, limit=20)
                query_counts["k8s"] += 1
                for event in events:
                    reason = event.get("reason", "")
                    if reason in ("BackOff", "OOMKilled", "Unhealthy", "Failed", "Killing"):
                        context.add_evidence(
                            source=TelemetrySource.KUBERNETES,
                            resource=f"{namespace}/{event.get('object_name', workload)}",
                            metric_or_query="kubectl get events",
                            observation=f"Event {reason} (count {event.get('count', 1)}): {event.get('message')}",
                            evidence_type=EvidenceType.FACT,
                            severity="WARN" if reason != "OOMKilled" else "CRITICAL",
                            raw_payload=event,
                        )
            except Exception as e:
                logger.error(f"Kubernetes evidence collection failed: {str(e)}")
                context.telemetry_status["kubernetes"].error_message = str(e)
        else:
            context.add_evidence(
                source=TelemetrySource.KUBERNETES,
                resource=f"{namespace}/{workload}",
                metric_or_query="kubectl",
                observation="Kubernetes API was unreachable or unavailable during investigation.",
                evidence_type=EvidenceType.FACT,
                severity="WARN",
            )

        # -------------------------------------------------------------
        # 2. Prometheus Investigation
        # -------------------------------------------------------------
        prom_available = self.prom_tools.client.is_available()
        context.telemetry_status["prometheus"] = TelemetryStatus(
            source=TelemetrySource.PROMETHEUS,
            available=prom_available,
        )

        if prom_available:
            try:
                # 2a. HTTP Error Rate
                error_rate = self.prom_tools.query_error_rate(app=workload, namespace=namespace)
                query_counts["prometheus"] += 1
                if error_rate is not None:
                    severity = "CRITICAL" if error_rate > 30 else ("WARN" if error_rate > 5 else "INFO")
                    context.add_evidence(
                        source=TelemetrySource.PROMETHEUS,
                        resource=workload,
                        metric_or_query="sum(rate(http_requests_total{status=~'5..'}))",
                        observation=f"HTTP 5xx error rate is currently {error_rate}% over the last 2m window.",
                        evidence_type=EvidenceType.FACT,
                        severity=severity,
                    )

                # 2b. Request breakdown
                requests_summary = self.prom_tools.query_request_summary(app=workload, namespace=namespace)
                query_counts["prometheus"] += 1
                if requests_summary:
                    formatted_summary = ", ".join(
                        f"{r['endpoint']} [{r['status']}]: {r['count']}" for r in requests_summary
                    )
                    context.add_evidence(
                        source=TelemetrySource.PROMETHEUS,
                        resource=workload,
                        metric_or_query="http_requests_total by endpoint, status",
                        observation=f"Request totals: {formatted_summary}",
                        evidence_type=EvidenceType.FACT,
                        severity="INFO",
                    )

                # 2c. Synthetic Memory Allocation
                mem_mb = self.prom_tools.query_synthetic_memory(app=workload)
                query_counts["prometheus"] += 1
                if mem_mb is not None and mem_mb > 0:
                    severity = "CRITICAL" if mem_mb > 80 else ("WARN" if mem_mb > 30 else "INFO")
                    context.add_evidence(
                        source=TelemetrySource.PROMETHEUS,
                        resource=workload,
                        metric_or_query="app_memory_allocated_bytes",
                        observation=f"Application synthetic memory allocation gauge reported {mem_mb} MB active allocation.",
                        evidence_type=EvidenceType.FACT,
                        severity=severity,
                    )
            except Exception as e:
                logger.error(f"Prometheus evidence collection failed: {str(e)}")
                context.telemetry_status["prometheus"].error_message = str(e)
        else:
            context.add_evidence(
                source=TelemetrySource.PROMETHEUS,
                resource=workload,
                metric_or_query="prometheus",
                observation="Prometheus server was unreachable or unavailable during investigation.",
                evidence_type=EvidenceType.FACT,
                severity="WARN",
            )

        # -------------------------------------------------------------
        # 3. Loki Investigation
        # -------------------------------------------------------------
        loki_available = self.loki_tools.client.is_available()
        context.telemetry_status["loki"] = TelemetryStatus(
            source=TelemetrySource.LOKI,
            available=loki_available,
        )

        if loki_available:
            try:
                # 3a. Recent Application Errors
                error_logs = self.loki_tools.search_error_logs(namespace=namespace, app=workload, limit=10)
                query_counts["loki"] += 1
                for log in error_logs:
                    msg = log.get("message") or log.get("raw", "")
                    err_type = log.get("error_type", "Error")
                    req_id = log.get("request_id")
                    obs = f"Application error log [{err_type}]: {msg}"
                    if req_id:
                        obs += f" (request_id={req_id})"

                    context.add_evidence(
                        source=TelemetrySource.LOKI,
                        resource=f"{namespace}/{workload}",
                        metric_or_query='{namespace=...} | json | level="ERROR"',
                        observation=obs,
                        evidence_type=EvidenceType.FACT,
                        severity="ERROR",
                        raw_payload=log,
                    )

                # 3b. Fatal Panics / Crashes
                crash_logs = self.loki_tools.search_fatal_crashes(namespace=namespace, app=workload, limit=5)
                query_counts["loki"] += 1
                for log in crash_logs:
                    msg = log.get("message") or log.get("raw", "")
                    context.add_evidence(
                        source=TelemetrySource.LOKI,
                        resource=f"{namespace}/{workload}",
                        metric_or_query='{namespace=...} |= "FATAL"',
                        observation=f"Fatal crash log captured: {msg}",
                        evidence_type=EvidenceType.FACT,
                        severity="CRITICAL",
                        raw_payload=log,
                    )

                # 3c. Memory Leak logs
                mem_logs = self.loki_tools.search_memory_leaks(namespace=namespace, app=workload, limit=5)
                query_counts["loki"] += 1
                for log in mem_logs:
                    msg = log.get("message") or log.get("raw", "")
                    context.add_evidence(
                        source=TelemetrySource.LOKI,
                        resource=f"{namespace}/{workload}",
                        metric_or_query='{namespace=...} |= "Memory allocation leak"',
                        observation=f"Memory leak warning log: {msg}",
                        evidence_type=EvidenceType.FACT,
                        severity="WARN",
                        raw_payload=log,
                    )
            except Exception as e:
                logger.error(f"Loki evidence collection failed: {str(e)}")
                context.telemetry_status["loki"].error_message = str(e)
        else:
            context.add_evidence(
                source=TelemetrySource.LOKI,
                resource=workload,
                metric_or_query="loki",
                observation="Loki log aggregation engine was unreachable or unavailable during investigation.",
                evidence_type=EvidenceType.FACT,
                severity="WARN",
            )

        context.telemetry_status["kubernetes"].query_count = query_counts["k8s"]
        context.telemetry_status["prometheus"].query_count = query_counts["prometheus"]
        context.telemetry_status["loki"].query_count = query_counts["loki"]

        return context, query_counts
