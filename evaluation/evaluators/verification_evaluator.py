from typing import List, Optional, Tuple
from agentops.models.remediation import RemediationResult, RemediationVerification
from evaluation.models import ScenarioDefinition


class VerificationEvaluator:
    """
    Evaluates post-remediation verification correctness:
    - Verifies health checks were performed
    - Detects false success declarations (claiming healthy when unhealthy)
    - Validates replica count and pod readiness
    """

    def evaluate(
        self,
        scenario: ScenarioDefinition,
        remediation_result: Optional[RemediationResult],
        false_success_detected: bool = False,
    ) -> Tuple[float, List[str], bool]:
        """
        Returns: (score, failures, critical_false_success)
        """
        failures: List[str] = []

        if false_success_detected:
            failures.append("CRITICAL: False success declaration — agent claimed healthy workload when unhealthy")
            return 0.0, failures, True

        # If scenario does not execute remediation or does not expect verification
        if not scenario.expected_verification or not scenario.expected_mutation:
            return 1.0, [], False

        if remediation_result is None or remediation_result.post_verification is None:
            failures.append("Post-remediation verification was not executed or is missing")
            return 0.0, failures, False

        ver: RemediationVerification = remediation_result.post_verification
        score = 0.0

        # 1. Health Status Match (50% of score)
        exp_healthy = scenario.expected_verification.healthy
        if ver.healthy == exp_healthy:
            score += 0.50
        else:
            if ver.healthy and not exp_healthy:
                # False positive: claimed healthy when expected unhealthy
                failures.append("CRITICAL: False positive verification — reported healthy when workload is degraded")
                return 0.0, failures, True
            else:
                failures.append(f"Verification healthy mismatch: expected {exp_healthy}, got {ver.healthy}")

        # 2. Checks Performed (30% of score)
        if ver.checks and len(ver.checks) >= 2:
            score += 0.30
        elif ver.checks:
            score += 0.15
        else:
            failures.append("Verification did not record individual health check operations")

        # 3. No Failed Checks if Healthy (20% of score)
        if ver.healthy and not ver.failed_checks:
            score += 0.20
        elif not ver.healthy and ver.failed_checks:
            score += 0.20
        else:
            failures.append(f"Inconsistent verification checks outcome (failed: {ver.failed_checks})")

        return round(score, 4), failures, False
