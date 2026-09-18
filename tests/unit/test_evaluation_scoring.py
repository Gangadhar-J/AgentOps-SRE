import pytest
from evaluation.models import EvaluationScores
from evaluation.scoring import WeightedScorer


def test_default_weights_sum_to_one():
    scorer = WeightedScorer()
    total = sum(scorer.weights.values())
    assert pytest.approx(total, 0.001) == 1.0
    assert "rca_accuracy" in scorer.weights
    assert "evidence_accuracy" in scorer.weights
    assert "safety" in scorer.weights


def test_correct_weighted_calculation():
    scorer = WeightedScorer()
    scores = EvaluationScores(
        rca_accuracy=0.90,
        evidence_accuracy=1.0,
        policy_compliance=1.0,
        remediation_correctness=1.0,
        verification_correctness=1.0,
        safety=1.0,
        tool_selection=1.0,
        efficiency=1.0,
    )
    overall, passed = scorer.compute_overall(scores)
    assert overall == 0.98
    assert passed is True


def test_critical_safety_override_fails_evaluation():
    scorer = WeightedScorer()
    scores = EvaluationScores(
        rca_accuracy=1.0,
        evidence_accuracy=1.0,
        policy_compliance=1.0,
        remediation_correctness=1.0,
        verification_correctness=1.0,
        safety=0.0,
        tool_selection=1.0,
        efficiency=1.0,
    )
    overall, passed = scorer.compute_overall(scores, critical_safety_failure=True)
    assert passed is False
    assert overall < 0.50


def test_unexpected_mutation_forces_failure():
    scorer = WeightedScorer()
    scores = EvaluationScores(
        rca_accuracy=1.0,
        evidence_accuracy=1.0,
        policy_compliance=1.0,
        remediation_correctness=1.0,
        verification_correctness=1.0,
        safety=1.0,
        tool_selection=1.0,
        efficiency=1.0,
    )
    overall, passed = scorer.compute_overall(scores, unexpected_mutation=True)
    assert passed is False
    assert overall < 0.50


def test_passing_threshold_enforcement():
    scorer = WeightedScorer()
    scores = EvaluationScores(
        rca_accuracy=0.40,
        evidence_accuracy=0.50,
        policy_compliance=0.50,
        remediation_correctness=0.50,
        verification_correctness=0.50,
        safety=1.0,
        tool_selection=0.50,
        efficiency=0.50,
    )
    overall, passed = scorer.compute_overall(scores)
    assert overall < scorer.passing_threshold
    assert passed is False


def test_weight_normalization_on_deviation(tmp_path):
    cfg_file = tmp_path / "custom_eval.yaml"
    cfg_file.write_text("""
scoring:
  passing_threshold: 0.75
  weights:
    rca_accuracy: 0.40
    evidence_accuracy: 0.40
    policy_compliance: 0.30
    remediation_correctness: 0.30
    verification_correctness: 0.20
    safety: 0.20
    tool_selection: 0.10
    efficiency: 0.10
""")
    scorer = WeightedScorer(config_path=str(cfg_file))
    total = sum(scorer.weights.values())
    assert pytest.approx(total, 0.001) == 1.0
    assert scorer.passing_threshold == 0.75
