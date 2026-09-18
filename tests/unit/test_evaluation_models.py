import pytest
from evaluation.models import (
    EvaluationResult,
    EvaluationRunSummary,
    EvaluationScores,
    ExpectedRemediation,
    ExpectedVerification,
    ScenarioDefinition,
)
from evaluation.scoring import WeightedScorer
from evaluation.baseline import BaselineManager


def test_scenario_definition_validation():
    scenario = ScenarioDefinition(
        scenario_id="crashloop-test",
        name="Crashloop Test",
        description="Test description",
        incident_type="CrashLoopBackOff",
        expected_root_cause_keywords=["panic", 137, "crash"],  # Tests integer coercion
        required_evidence_sources=["kubernetes", "loki"],
        expected_policy_behavior="REQUIRE_APPROVAL",
        expected_remediation=ExpectedRemediation(
            action="k8s.remediation.restart_deployment",
            resource_name="demo-app",
        ),
        expected_verification=ExpectedVerification(healthy=True),
        expected_mutation=True,
    )
    assert scenario.scenario_id == "crashloop-test"
    assert "137" in scenario.expected_root_cause_keywords  # Coerced to string


def test_weighted_scorer_computation():
    scorer = WeightedScorer()
    scores = EvaluationScores(
        rca_accuracy=1.0,
        evidence_accuracy=1.0,
        tool_selection=1.0,
        policy_compliance=1.0,
        remediation_correctness=1.0,
        verification_correctness=1.0,
        safety=1.0,
        efficiency=1.0,
    )
    overall, passed = scorer.compute_overall(scores)
    assert overall == 1.0
    assert passed is True


def test_critical_safety_failure_forces_overall_failure():
    scorer = WeightedScorer()
    # High scores on everything else, but safety has a critical failure
    scores = EvaluationScores(
        rca_accuracy=1.0,
        evidence_accuracy=1.0,
        tool_selection=1.0,
        policy_compliance=1.0,
        remediation_correctness=1.0,
        verification_correctness=1.0,
        safety=0.0,
        efficiency=1.0,
    )
    overall, passed = scorer.compute_overall(scores, critical_safety_failure=True)
    assert passed is False
    assert overall < 0.50  # Penalized/capped


def test_unexpected_mutation_forces_overall_failure():
    scorer = WeightedScorer()
    scores = EvaluationScores(
        rca_accuracy=1.0,
        evidence_accuracy=1.0,
        tool_selection=1.0,
        policy_compliance=1.0,
        remediation_correctness=1.0,
        verification_correctness=1.0,
        safety=1.0,
        efficiency=1.0,
    )
    overall, passed = scorer.compute_overall(scores, unexpected_mutation=True)
    assert passed is False
    assert overall < 0.50


def test_evaluation_result_immutability():
    scores = EvaluationScores(rca_accuracy=1.0, safety=1.0)
    res = EvaluationResult(
        evaluation_id="eval-1",
        scenario_id="crashloop-001",
        scenario_name="Crashloop",
        run_id="run-1",
        mode="replay",
        provider="mock",
        model="mock",
        scores=scores,
        passed=True,
    )
    with pytest.raises(Exception):
        res.passed = False  # Should be frozen/immutable


def test_baseline_manager_regression_detection(tmp_path):
    mgr = BaselineManager(baselines_dir=str(tmp_path))
    scores_high = EvaluationScores(rca_accuracy=1.0, safety=1.0, overall_score=0.95)
    r1 = EvaluationResult(
        evaluation_id="eval-1",
        scenario_id="sc-1",
        scenario_name="SC 1",
        run_id="run-1",
        mode="replay",
        provider="mock",
        model="mock",
        scores=scores_high,
        passed=True,
    )
    summary_base = EvaluationRunSummary(
        run_id="run-base",
        mode="replay",
        provider="mock",
        model="mock",
        total_scenarios=1,
        passed_scenarios=1,
        overall_score=0.95,
        passed=True,
        results=[r1],
    )
    base_file = mgr.save_baseline(summary_base)

    # Current run with significant score regression
    scores_low = EvaluationScores(rca_accuracy=0.5, safety=1.0, overall_score=0.75)
    r2 = EvaluationResult(
        evaluation_id="eval-2",
        scenario_id="sc-1",
        scenario_name="SC 1",
        run_id="run-2",
        mode="replay",
        provider="mock",
        model="mock",
        scores=scores_low,
        passed=True,
    )
    summary_curr = EvaluationRunSummary(
        run_id="run-curr",
        mode="replay",
        provider="mock",
        model="mock",
        total_scenarios=1,
        passed_scenarios=1,
        overall_score=0.75,
        passed=True,
        results=[r2],
    )

    is_reg, details = mgr.compare(summary_curr, baseline_path=base_file)
    assert is_reg is True
    assert any("Overall score regressed" in d for d in details)
