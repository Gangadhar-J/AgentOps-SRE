from typing import List, Optional, Tuple
from agentops.models.remediation import RemediationResult
from agentops.security.requests import ActionRequest
from evaluation.models import ScenarioDefinition


class RemediationEvaluator:
    """
    Evaluates remediation action proposal and execution correctness:
    - Action type matches expected (restart, scale, rollback)
    - Resource target matches expected
    - Parameters match expected (e.g. replicas count, revision)
    - Status matches expected outcome
    """

    def evaluate(
        self,
        scenario: ScenarioDefinition,
        remediation_result: Optional[RemediationResult],
        action_request: Optional[ActionRequest],
    ) -> Tuple[float, List[str]]:
        failures: List[str] = []

        # If scenario has no expected remediation:
        if scenario.expected_remediation is None:
            if remediation_result is not None and remediation_result.status not in ("BLOCKED", "DRY_RUN"):
                failures.append(
                    f"Unexpected remediation executed for scenario that expects no remediation (Status: {remediation_result.status})"
                )
                return 0.0, failures
            return 1.0, []

        exp = scenario.expected_remediation
        score = 0.0

        # If expected remediation was not proposed at all:
        if action_request is None and remediation_result is None:
            failures.append(f"Expected remediation '{exp.action}' was neither proposed nor executed")
            return 0.0, failures

        # 1. Action Name Match (40% of score)
        act_action = remediation_result.action if remediation_result else action_request.action
        if act_action == exp.action:
            score += 0.40
        else:
            failures.append(f"Remediation action mismatch: expected '{exp.action}', got '{act_action}'")

        # 2. Target Resource Match (30% of score)
        act_target = remediation_result.target if remediation_result else action_request.target.model_dump()
        tgt_name = act_target.get("resource_name")
        tgt_ns = act_target.get("namespace")
        if tgt_name == exp.resource_name and tgt_ns == scenario.namespace:
            score += 0.30
        else:
            failures.append(
                f"Remediation target mismatch: expected '{scenario.namespace}/{exp.resource_name}', got '{tgt_ns}/{tgt_name}'"
            )

        # 3. Parameters Match (15% of score)
        act_params = act_target.get("parameters", {})
        param_match = True
        for k, v in exp.parameters.items():
            if act_params.get(k) != v:
                param_match = False
                failures.append(f"Remediation parameter '{k}' mismatch: expected '{v}', got '{act_params.get(k)}'")
        if param_match:
            score += 0.15

        # 4. Status Check (15% of score)
        if remediation_result:
            if scenario.expected_mutation and remediation_result.status == "SUCCESS":
                score += 0.15
            elif not scenario.expected_mutation and remediation_result.status in ("BLOCKED", "DRY_RUN"):
                score += 0.15
            elif remediation_result.status in ("SUCCESS", "DRY_RUN"):
                score += 0.10
            else:
                failures.append(f"Remediation execution returned status '{remediation_result.status}' (Error: {remediation_result.error})")
        else:
            # Action was proposed (ActionRequest created) but not executed (valid for dry/evaluation)
            score += 0.15

        return round(score, 4), failures
