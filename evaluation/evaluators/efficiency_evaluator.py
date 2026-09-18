from typing import Any, Dict, List, Optional, Tuple
from evaluation.models import ScenarioDefinition


class EfficiencyEvaluator:
    """
    Evaluates agent resource consumption, latency, tool call count,
    and token usage. Null-safe for missing token metrics.
    """

    def evaluate(
        self,
        scenario: ScenarioDefinition,
        duration_seconds: float,
        tool_call_count: int,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> Tuple[float, List[str], Dict[str, Any]]:
        failures: List[str] = []
        metrics: Dict[str, Any] = {
            "duration_seconds": round(duration_seconds, 3),
            "tool_call_count": tool_call_count,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

        score = 0.0

        # 1. Latency / Execution Time (50% of efficiency score)
        max_duration = scenario.max_duration_seconds
        if duration_seconds <= (max_duration * 0.3):
            score += 0.50
        elif duration_seconds <= (max_duration * 0.7):
            score += 0.35
        elif duration_seconds <= max_duration:
            score += 0.20
        else:
            failures.append(
                f"Execution duration ({duration_seconds:.2f}s) exceeded limit ({max_duration:.2f}s)"
            )

        # 2. Tool Invocation Efficiency (30% of efficiency score)
        max_tools = scenario.max_allowed_tool_calls
        if tool_call_count <= (max_tools * 0.6):
            score += 0.30
        elif tool_call_count <= max_tools:
            score += 0.20
        else:
            failures.append(
                f"Tool invocation count ({tool_call_count}) exceeded target ({max_tools})"
            )

        # 3. Token Efficiency (20% of efficiency score)
        # Null-safe: if tokens are None (e.g. mock or provider without usage), grant default credit
        if prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens
            metrics["total_tokens"] = total_tokens
            if total_tokens < 4000:
                score += 0.20
            elif total_tokens < 10000:
                score += 0.10
            else:
                failures.append(f"High token consumption: {total_tokens} tokens")
        else:
            # Neutral credit when tokens not tracked
            score += 0.20

        return round(score, 4), failures, metrics
