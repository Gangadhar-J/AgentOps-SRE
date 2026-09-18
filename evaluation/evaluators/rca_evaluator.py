from typing import List, Optional, Tuple
from agentops.models.rca import RootCauseAnalysis
from evaluation.models import ScenarioDefinition


class RCAEvaluator:
    """
    Evaluates RCA correctness using structured criteria:
    - Incident type matching
    - Keyword coverage in root cause diagnosis
    - Confidence threshold
    - Non-empty actionable recommendations
    """

    def evaluate(
        self,
        scenario: ScenarioDefinition,
        rca: Optional[RootCauseAnalysis],
    ) -> Tuple[float, List[str]]:
        failures: List[str] = []
        if rca is None:
            return 0.0, ["RCA is missing; agent did not produce an investigation outcome."]

        score = 0.0

        # 1. Incident Type Accuracy (40% of RCA score)
        expected_type = scenario.incident_type.lower()
        actual_type = rca.incident_type.value.lower() if hasattr(rca.incident_type, "value") else str(rca.incident_type).lower()

        if actual_type == expected_type:
            score += 0.40
        else:
            failures.append(f"Incident type mismatch: expected '{scenario.incident_type}', got '{rca.incident_type}'")

        # 2. Root Cause Diagnostic Keywords (30% of RCA score)
        if scenario.expected_root_cause_keywords:
            rc_lower = rca.root_cause.lower()
            matched = [kw for kw in scenario.expected_root_cause_keywords if kw.lower() in rc_lower]
            keyword_ratio = len(matched) / len(scenario.expected_root_cause_keywords)
            score += 0.30 * keyword_ratio
            if keyword_ratio < 0.5:
                failures.append(
                    f"Root cause explanation missing required diagnostic keywords (matched: {matched}, expected: {scenario.expected_root_cause_keywords})"
                )
        else:
            # If no specific keywords defined, full keyword marks for non-empty root cause
            if len(rca.root_cause.strip()) > 20:
                score += 0.30

        # 3. Confidence Score (15% of RCA score)
        if rca.confidence >= 0.70:
            score += 0.15
        elif rca.confidence >= 0.50:
            score += 0.08
        else:
            failures.append(f"RCA confidence ({rca.confidence}) is below acceptable threshold (0.70)")

        # 4. Actionable Recommendation (15% of RCA score)
        if rca.recommended_action and len(rca.recommended_action.strip()) > 15:
            score += 0.15
        else:
            failures.append("RCA missing clear recommended remediation action")

        return round(score, 4), failures
