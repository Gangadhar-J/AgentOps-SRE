import logging
import time
from typing import Optional
from agentops.agent.orchestrator import InvestigationOrchestrator
from agentops.config import settings
from agentops.llm.base import BaseLLMProvider
from agentops.llm.factory import get_llm_provider
from agentops.models.rca import AgentObservabilityMetrics, RootCauseAnalysis

logger = logging.getLogger("agentops.investigator")


class SREAgent:
    """
    Controlled AI-Assisted SRE Agent for incident investigation and RCA synthesis.
    """

    def __init__(
        self,
        orchestrator: Optional[InvestigationOrchestrator] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
    ):
        self.orchestrator = orchestrator or InvestigationOrchestrator()
        self.llm_provider = llm_provider or get_llm_provider()

    def investigate(self, namespace: Optional[str] = None, workload: str = "demo-app") -> RootCauseAnalysis:
        """
        Execute full incident investigation:
        1. Collect deterministic multi-signal evidence.
        2. Reason over evidence via LLM Provider.
        3. Validate and attach agent self-observability metrics.
        """
        start_time = time.time()
        ns = namespace or settings.DEFAULT_NAMESPACE

        logger.info(f"Starting incident investigation for workload '{workload}' in namespace '{ns}'")

        # Step 1: Gather multi-modal evidence context
        context, query_counts = self.orchestrator.collect_evidence(namespace=ns, workload=workload)

        # Step 2: Reason over evidence to generate Root Cause Analysis
        errors = []
        try:
            rca, llm_meta = self.llm_provider.generate_rca(context)
        except Exception as e:
            logger.error(f"Primary RCA generation failed: {str(e)}")
            errors.append(str(e))
            # Retry once with mock provider if external LLM failed
            from agentops.llm.mock_provider import MockRuleBasedLLMProvider
            fallback = MockRuleBasedLLMProvider()
            rca, llm_meta = fallback.generate_rca(context)

        total_duration = round(time.time() - start_time, 3)

        # Step 3: Record agent self-observability metrics
        telemetry_avail = {
            k: v.available for k, v in context.telemetry_status.items()
        }
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
            errors=errors,
            telemetry_availability=telemetry_avail,
        )
        rca.agent_metrics = agent_metrics

        logger.info(
            f"Investigation {rca.investigation_id} completed in {total_duration}s. "
            f"Diagnosis: {rca.incident_type} (Confidence: {rca.confidence})"
        )
        return rca
