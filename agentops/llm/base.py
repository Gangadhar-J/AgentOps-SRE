import abc
import json
import logging
from typing import Any, Dict, Optional, Tuple
from agentops.models.evidence import InvestigationContext
from agentops.models.rca import RootCauseAnalysis

logger = logging.getLogger("agentops.llm")

RCA_SYSTEM_PROMPT = """You are an expert AI Site Reliability Engineer (AI SRE) analyzing an infrastructure incident.

Your task is to review the provided InvestigationContext and produce a structured, evidence-backed Root Cause Analysis (RCA).

CRITICAL INSTRUCTIONS:
1. ONLY reason over facts and telemetry provided in the InvestigationContext.
2. NEVER invent, fabricate, or hallucinate metrics, logs, or pod statuses that are not in the evidence.
3. If a telemetry source (Prometheus, Loki, or Kubernetes) is marked as unavailable or returned no data, explicitly mention that limitation.
4. In the 'evidence_ids' field, reference ONLY the IDs (e.g. ["E001", "E002"]) from the provided evidence items that directly support your conclusion.
5. 'requires_human_approval' MUST ALWAYS BE TRUE for any proposed remediation.
6. Provide a confidence score between 0.0 and 1.0 reflecting telemetry coverage and evidence agreement:
   - High (0.85 - 1.0): Multiple independent sources (K8s + Prometheus + Loki) confirm the failure mode.
   - Medium (0.5 - 0.84): One source is clear, but another is missing or partial.
   - Low (0.0 - 0.49): Insufficient or conflicting evidence.

Return ONLY a valid JSON object matching the RootCauseAnalysis schema.
"""


class BaseLLMProvider(abc.ABC):
    """
    Abstract Base Class for LLM reasoning providers.
    """

    @abc.abstractmethod
    def generate_rca(self, context: InvestigationContext) -> Tuple[RootCauseAnalysis, Dict[str, Any]]:
        """
        Synthesize a structured RootCauseAnalysis from the collected evidence.
        Returns (RootCauseAnalysis, metadata_dict).
        """
        pass

    def _validate_and_parse_rca(self, raw_json: str, investigation_id: str) -> RootCauseAnalysis:
        """
        Validates that LLM output adheres strictly to RootCauseAnalysis Pydantic schema.
        """
        try:
            # Strip markdown formatting if present
            cleaned = raw_json.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            parsed = json.loads(cleaned)
            parsed["investigation_id"] = investigation_id
            return RootCauseAnalysis.model_validate(parsed)
        except Exception as e:
            logger.error(f"Failed to validate LLM response against RCA schema: {str(e)}\nRaw: {raw_json}")
            raise ValueError(f"Invalid RCA structured output from LLM: {str(e)}") from e
