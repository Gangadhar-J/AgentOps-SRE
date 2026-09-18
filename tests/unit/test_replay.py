import pytest
from evaluation.engine import EvaluationEngine


def test_replay_mode_executes_deterministically():
    engine = EvaluationEngine()
    # Run the same replay scenario twice
    res1 = engine.run_scenario("crashloop-001", mode="replay", provider_name="mock")
    res2 = engine.run_scenario("crashloop-001", mode="replay", provider_name="mock")

    assert res1.passed is True
    assert res2.passed is True
    assert res1.scores.overall_score == res2.scores.overall_score
    assert res1.scores.rca_accuracy == res2.scores.rca_accuracy
    assert res1.scores.evidence_accuracy == res2.scores.evidence_accuracy
    assert res1.scores.safety == res2.scores.safety


def test_replay_mode_never_mutates_infrastructure():
    engine = EvaluationEngine()
    for sc_id in engine.discover_scenarios():
        res = engine.run_scenario(sc_id, mode="replay", provider_name="mock")
        # In replay mode, infrastructure must NEVER be mutated
        assert res.infrastructure_mutated is False
        assert res.unexpected_mutation is False
        assert res.mutation_count == 0
        assert res.critical_safety_failure is False


def test_replay_missing_fixture_raises_filenotfound():
    engine = EvaluationEngine()
    with pytest.raises(FileNotFoundError):
        engine.load_replay_fixture("non-existent-scenario-999")


def test_replay_loads_all_existing_fixtures():
    engine = EvaluationEngine()
    for sc_id in engine.discover_scenarios():
        fixture = engine.load_replay_fixture(sc_id)
        assert isinstance(fixture, dict)
        assert "evidence_items" in fixture
        assert "invoked_tools" in fixture


def test_replay_supports_short_scenario_names():
    engine = EvaluationEngine()
    # Loading by short name (e.g. crashloop instead of crashloop-001)
    scenario = engine.load_scenario("crashloop")
    assert scenario.scenario_id == "crashloop-001"

    res = engine.run_scenario("crashloop", mode="replay", provider_name="mock")
    assert res.passed is True
