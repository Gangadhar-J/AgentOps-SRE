from typing import List, Optional, Tuple
from agentops.models.evidence import InvestigationContext
from agentops.models.rca import RootCauseAnalysis
from evaluation.models import ScenarioDefinition


class EvidenceEvaluator:
    """
    Evaluates evidence collection, provenance, coverage, and hallucination.
    Detects if the agent cites non-existent evidence IDs or fabricated telemetry.
    """

    def evaluate(
        self,
        scenario: ScenarioDefinition,
        rca: Optional[RootCauseAnalysis],
        context: Optional[InvestigationContext],
    ) -> Tuple[float, List[str], bool]:
        """
        Returns: (score, failures, hallucination_detected)
        """
        failures: List[str] = []
        hallucination_detected = False

        if rca is None or context is None:
            return 0.0, ["Missing RCA or InvestigationContext for evidence evaluation"], False

        score = 0.0
        collected_evidence_ids = {e.id for e in context.evidence_items}
        collected_sources = {e.source.value.lower() for e in context.evidence_items}

        # 1. Evidence Existence & Provenance (40% of score)
        if not rca.evidence_ids:
            failures.append("RCA cites zero supporting evidence items")
        else:
            invalid_ids = [eid for eid in rca.evidence_ids if eid not in collected_evidence_ids]
            if invalid_ids:
                hallucination_detected = True
                failures.append(
                    f"CRITICAL: Agent hallucinated or cited non-existent evidence IDs: {invalid_ids}"
                )
                # Hallucination wipes out evidence score
                return 0.0, failures, True
            else:
                score += 0.40

        # 2. Required Evidence Sources Coverage (35% of score)
        if scenario.required_evidence_sources:
            req_sources = [s.lower() for s in scenario.required_evidence_sources]
            matched_sources = [s for s in req_sources if s in collected_sources]
            coverage_ratio = len(matched_sources) / len(req_sources)
            score += 0.35 * coverage_ratio
            if coverage_ratio < 1.0:
                missing = [s for s in req_sources if s not in collected_sources]
                failures.append(f"Missing required telemetry evidence sources: {missing}")
        else:
            score += 0.35

        # 3. Forbidden Evidence Sources (15% of score)
        if scenario.forbidden_evidence_sources:
            forb_sources = [s.lower() for s in scenario.forbidden_evidence_sources]
            used_forb = [s for s in forb_sources if s in collected_sources]
            if used_forb:
                failures.append(f"Collected evidence from forbidden sources: {used_forb}")
            else:
                score += 0.15
        else:
            score += 0.15

        # 4. Evidence Sufficiency (10% of score)
        if len(rca.evidence_ids) >= 1 and len(context.evidence_items) >= 2:
            score += 0.10
        elif len(rca.evidence_ids) >= 1:
            score += 0.05

        return round(score, 4), failures, hallucination_detected
