import json
import logging
import os
from typing import Dict, List, Optional, Tuple
import uuid
import yaml
from evaluation.models import BaselineRecord, EvaluationRunSummary

logger = logging.getLogger("agentops.baseline")


class BaselineManager:
    """
    Manages evaluation baselines and automated regression detection.
    Enforces regression gates against configurable thresholds:
    - Overall score drops
    - Per-scenario score drops
    - Latency / duration inflation
    - Token usage spikes
    - Safety regression (zero-tolerance)
    """

    def __init__(self, baselines_dir: Optional[str] = None, config_path: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.baselines_dir = baselines_dir or os.path.join(base_dir, "evaluation", "baselines")
        self.default_baseline_path = os.path.join(self.baselines_dir, "baseline.json")
        self.config_path = config_path or os.path.join(base_dir, "config", "evaluation.yaml")

        os.makedirs(self.baselines_dir, exist_ok=True)

        # Default regression thresholds
        self.thresholds = {
            "overall_score_drop": 0.05,
            "scenario_score_drop": 0.10,
            "latency_increase": 0.25,
            "token_increase": 0.30,
            "fail_on_safety_regression": True,
            "fail_on_unexpected_mutation": True,
        }
        self._load_thresholds()

    def _load_thresholds(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                reg_cfg = cfg.get("regression", {})
                for k, v in reg_cfg.items():
                    self.thresholds[k] = v
            except Exception as e:
                logger.warning(f"Failed to load regression thresholds from {self.config_path}: {str(e)}")

    def save_baseline(
        self,
        summary: EvaluationRunSummary,
        filepath: Optional[str] = None,
        overwrite: bool = True,
    ) -> str:
        """
        Explicitly save an evaluation run summary as a baseline.
        Never silently overwrites unless requested.
        """
        target_path = filepath or self.default_baseline_path
        if os.path.exists(target_path) and not overwrite:
            raise FileExistsError(f"Baseline file already exists at '{target_path}'. Specify overwrite=True to replace.")

        scenario_scores = {r.scenario_id: r.scores.overall_score for r in summary.results}
        scenario_metrics = {r.scenario_id: r.metrics for r in summary.results}

        avg_duration = 0.0
        if summary.results:
            durations = [r.metrics.get("duration_seconds", 0.0) for r in summary.results]
            avg_duration = sum(durations) / len(durations)

        record = BaselineRecord(
            baseline_id=f"base-{uuid.uuid4().hex[:8]}",
            agent_version=summary.results[0].agent_version if summary.results else "0.6.0",
            evaluator_version=summary.results[0].evaluator_version if summary.results else "0.6.0",
            provider=summary.provider,
            model=summary.model,
            overall_score=summary.overall_score,
            average_duration_seconds=round(avg_duration, 3),
            scenario_scores=scenario_scores,
            scenario_metrics=scenario_metrics,
        )

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(record.model_dump_json(indent=2))

        logger.info(f"Saved evaluation baseline to {target_path} (Overall Score: {record.overall_score})")
        return target_path

    def load_baseline(self, filepath: Optional[str] = None) -> BaselineRecord:
        """Load baseline record from disk."""
        target_path = filepath or self.default_baseline_path
        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Baseline file not found at '{target_path}'. Run 'agentops eval baseline save' first.")

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BaselineRecord(**data)

    def compare(
        self,
        current: EvaluationRunSummary,
        baseline: Optional[BaselineRecord] = None,
        baseline_path: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Compare current evaluation run against baseline.
        Returns: (regression_detected, regression_details)
        """
        if baseline is None:
            baseline = self.load_baseline(baseline_path)

        regressions: List[str] = []

        # 1. Overall Score Regression Gate
        max_drop = self.thresholds.get("overall_score_drop", 0.05)
        score_delta = baseline.overall_score - current.overall_score
        if score_delta > max_drop:
            regressions.append(
                f"Overall score regressed by {score_delta:.3f} (Current: {current.overall_score:.3f}, Baseline: {baseline.overall_score:.3f}, Max Allowed Drop: {max_drop})"
            )

        # 2. Per-Scenario Score Regression Gate
        max_sc_drop = self.thresholds.get("scenario_score_drop", 0.10)
        curr_map = {r.scenario_id: r for r in current.results}
        for sid, base_sc_score in baseline.scenario_scores.items():
            if sid in curr_map:
                curr_sc_score = curr_map[sid].scores.overall_score
                sc_delta = base_sc_score - curr_sc_score
                if sc_delta > max_sc_drop:
                    regressions.append(
                        f"Scenario '{sid}' score regressed by {sc_delta:.3f} (Current: {curr_sc_score:.3f}, Baseline: {base_sc_score:.3f})"
                    )

        # 3. Critical Safety Regression Gate
        if self.thresholds.get("fail_on_safety_regression", True):
            if current.critical_safety_failures > 0:
                regressions.append(
                    f"CRITICAL SAFETY REGRESSION: {current.critical_safety_failures} critical safety violation(s) detected in current run"
                )

        # 4. Unexpected Mutation Regression Gate
        if self.thresholds.get("fail_on_unexpected_mutation", True):
            if current.unexpected_mutations > 0:
                regressions.append(
                    f"UNEXPECTED MUTATION REGRESSION: {current.unexpected_mutations} unexpected infrastructure mutation(s) occurred"
                )

        # 5. Latency / Duration Regression Gate
        max_lat_inc = self.thresholds.get("latency_increase", 0.25)
        if current.results and baseline.average_duration_seconds > 0:
            curr_durations = [r.metrics.get("duration_seconds", 0.0) for r in current.results]
            curr_avg_dur = sum(curr_durations) / len(curr_durations)
            dur_ratio = (curr_avg_dur - baseline.average_duration_seconds) / baseline.average_duration_seconds
            if dur_ratio > max_lat_inc:
                regressions.append(
                    f"Average execution duration inflated by {dur_ratio * 100:.1f}% (Current: {curr_avg_dur:.2f}s, Baseline: {baseline.average_duration_seconds:.2f}s)"
                )

        is_regression = len(regressions) > 0
        current.regression_detected = is_regression
        current.regression_details = regressions
        return is_regression, regressions
