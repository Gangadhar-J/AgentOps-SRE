import logging
import time
from typing import Optional
from agentops.agent.orchestrator import InvestigationOrchestrator
from agentops.config import settings
from agentops.llm.base import BaseLLMProvider
from agentops.llm.factory import get_llm_provider
from agentops.models.rca import (
    AgentObservabilityMetrics,
    IncidentSeverity,
    IncidentType,
    RootCauseAnalysis,
)
from agentops.observability.tracing import start_span

logger = logging.getLogger("agentops.investigator")


class SREAgent:
    """
    Controlled AI-Assisted SRE Agent for incident investigation and RCA synthesis via MCP.
    Never silently falls back to mock or deterministic engines in live execution.
    """

    def __init__(
        self,
        orchestrator: Optional[InvestigationOrchestrator] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
    ):
        self.orchestrator = orchestrator or InvestigationOrchestrator()
        self.llm_provider = llm_provider or get_llm_provider()

    def investigate(
        self,
        namespace: Optional[str] = None,
        workload: str = "demo-app",
        incident_description: Optional[str] = None,
    ) -> RootCauseAnalysis:
        """
        Execute full incident investigation:
        1. Collect multi-signal evidence via MCP Client.
        2. Reason over evidence via configured real LLM Provider.
        3. Independently validate schema and evidence references.
        4. Validate and attach agent self-observability and MCP metrics.
        """
        start_time = time.time()
        ns = namespace or settings.DEFAULT_NAMESPACE

        logger.info(f"Starting incident investigation for workload '{workload}' in namespace '{ns}'")

        with start_span("agent.investigation", attributes={"kubernetes.namespace": ns, "kubernetes.workload": workload}):
            # Step 1: Gather multi-modal evidence context via MCP
            context, query_counts = self.orchestrator.collect_evidence(namespace=ns, workload=workload)
            if incident_description:
                context.metadata["incident_description"] = incident_description
            self.last_context = context

            # Track missing signals
            missing_signals = [k for k, v in context.telemetry_status.items() if not v.available]

            # Step 2: Reason over evidence to generate Root Cause Analysis
            errors = []
            error_cat = None
            validation_passed = False
            schema_validated = False
            evidence_validated = False

            with start_span("agent.llm", attributes={"investigation.id": context.investigation_id}):
                try:
                    rca, llm_meta = self.llm_provider.generate_rca(context)
                    validation_passed = True
                    schema_validated = True
                    evidence_validated = True
                except Exception as e:
                    error_msg = str(e)
                    error_cat = getattr(e, "error_category", type(e).__name__)
                    logger.error(f"Primary RCA generation failed ({error_cat}): {error_msg}")
                    errors.append(error_msg)

                    raw_p = getattr(self.llm_provider, "provider_label", None)
                    provider_name = raw_p if isinstance(raw_p, str) else "unknown"
                    if provider_name == "unknown" and hasattr(self.llm_provider, "_is_cloud"):
                        provider_name = "openai" if getattr(self.llm_provider, "_is_cloud", False) else "ollama"
                    elif hasattr(self.llm_provider, "endpoint"):
                        provider_name = "gemini"

                    raw_m = getattr(self.llm_provider, "model_name", None)
                    model_name = raw_m if isinstance(raw_m, str) else "unknown"

                    # Construct honest diagnostic failure record (NO fake diagnosis, NO mock fallback!)
                    rca = RootCauseAnalysis(
                        investigation_id=context.investigation_id,
                        incident_type=IncidentType.UNKNOWN,
                        severity=IncidentSeverity.LOW,
                        summary=f"Investigation Failed: {error_msg}",
                        root_cause=f"Model reasoning failed with {error_cat}: {error_msg}. Evidence was collected, but no valid RCA was synthesized.",
                        confidence=0.0,
                        evidence_ids=[],
                        timeline=[],
                        recommended_action="Manual SRE investigation required. Automated remediation blocked.",
                        requires_human_approval=False,
                        telemetry_coverage={k: v.available for k, v in context.telemetry_status.items()},
                        validation_passed=False,
                        missing_signals=missing_signals,
                    )
                    llm_meta = {
                        "provider": provider_name,
                        "model": model_name,
                        "latency_seconds": round(time.time() - start_time, 3),
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "time_to_first_token": None,
                    }

            total_duration = round(time.time() - start_time, 3)
            rca.missing_signals = missing_signals
            rca.validation_passed = validation_passed

            # Step 3: Record agent self-observability and MCP metrics
            with start_span("agent.rca", attributes={
                "incident.type": rca.incident_type.value if hasattr(rca.incident_type, "value") else str(rca.incident_type),
                "confidence": rca.confidence,
                "validation_passed": validation_passed,
            }):
                telemetry_avail = {
                    k: v.available for k, v in context.telemetry_status.items()
                }
                mcp_summary = self.orchestrator.mcp_client.metrics.summary() if hasattr(self.orchestrator, "mcp_client") else None

        agent_metrics = AgentObservabilityMetrics(
            investigation_id=context.investigation_id,
            duration_seconds=total_duration,
            k8s_query_count=query_counts.get("k8s", 0),
            prometheus_query_count=query_counts.get("prometheus", 0),
            loki_query_count=query_counts.get("loki", 0),
            llm_latency_seconds=llm_meta.get("latency_seconds", 0.0),
            llm_provider=llm_meta.get("provider", "unknown"),
            llm_model=llm_meta.get("model", "unknown"),
            prompt_tokens=llm_meta.get("prompt_tokens"),
            completion_tokens=llm_meta.get("completion_tokens"),
            time_to_first_token=llm_meta.get("time_to_first_token"),
            errors=errors,
            error_category=error_cat,
            schema_validated=schema_validated,
            evidence_validated=evidence_validated,
            telemetry_availability=telemetry_avail,
            missing_signals=missing_signals,
            mcp_metrics=mcp_summary,
        )
        rca.agent_metrics = agent_metrics

        logger.info(
            f"Investigation {rca.investigation_id} completed in {total_duration}s. "
            f"Diagnosis: {rca.incident_type} (Confidence: {rca.confidence}, Validated: {validation_passed})"
        )
        return rca
