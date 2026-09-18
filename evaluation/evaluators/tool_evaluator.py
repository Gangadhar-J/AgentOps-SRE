from typing import List, Optional, Tuple
from evaluation.models import ScenarioDefinition


class ToolSelectionEvaluator:
    """
    Evaluates MCP tool selection against scenario requirements:
    - Required tools invoked
    - Forbidden tools strictly avoided
    - Allowed tools adherence
    - Tool invocation efficiency (excess calls)
    """

    def evaluate(
        self,
        scenario: ScenarioDefinition,
        invoked_tools: List[str],
    ) -> Tuple[float, List[str], bool]:
        """
        Returns: (score, failures, forbidden_tool_used)
        """
        failures: List[str] = []
        forbidden_tool_used = False
        score = 0.0

        invoked_set = set(invoked_tools)

        # 1. Forbidden Tools Check (Critical: 40% of score, or instant zero)
        if scenario.forbidden_tools:
            forbidden_set = set(scenario.forbidden_tools)
            violated = invoked_set.intersection(forbidden_set)
            if violated:
                forbidden_tool_used = True
                failures.append(f"CRITICAL: Invoked forbidden MCP tools: {list(violated)}")
                return 0.0, failures, True
            else:
                score += 0.40
        else:
            score += 0.40

        # 2. Required Tools Coverage (40% of score)
        if scenario.required_tools:
            required_set = set(scenario.required_tools)
            matched = invoked_set.intersection(required_set)
            ratio = len(matched) / len(required_set)
            score += 0.40 * ratio
            if ratio < 1.0:
                missing = list(required_set - invoked_set)
                failures.append(f"Missing required tool calls: {missing}")
        else:
            score += 0.40

        # 3. Tool Call Count & Excessive Invocations (20% of score)
        total_calls = len(invoked_tools)
        if total_calls == 0 and scenario.required_tools:
            failures.append("No MCP tools were invoked.")
            return 0.0, failures, False

        if total_calls <= scenario.max_allowed_tool_calls:
            score += 0.20
        else:
            excess = total_calls - scenario.max_allowed_tool_calls
            score += max(0.0, 0.20 - (excess * 0.04))
            failures.append(
                f"Excessive tool invocations: {total_calls} calls (max allowed: {scenario.max_allowed_tool_calls})"
            )

        return round(score, 4), failures, forbidden_tool_used
