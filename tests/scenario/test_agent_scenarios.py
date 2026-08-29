import subprocess
import time
import requests
import pytest
from agentops.agent.investigator import SREAgent
from agentops.llm.mock_provider import MockRuleBasedLLMProvider
from agentops.models.rca import IncidentType

DEMO_APP_URL = "http://localhost:30080"


@pytest.fixture(autouse=True)
def reset_cluster():
    # Reset before test
    subprocess.run(["./scripts/trigger-incident.sh", "reset"], check=True, capture_output=True)
    time.sleep(2)
    yield
    # Reset after test
    subprocess.run(["./scripts/trigger-incident.sh", "reset"], check=True, capture_output=True)


def test_investigate_high_error_rate_scenario():
    # 1. Trigger high error rate incident (already sends traffic and restarts)
    subprocess.run(["./scripts/trigger-incident.sh", "high-error-rate"], check=True, capture_output=True)
    time.sleep(3)

    # 2. Run SRE Agent Investigation
    agent = SREAgent(llm_provider=MockRuleBasedLLMProvider())
    rca = agent.investigate(namespace="demo", workload="demo-app")

    # 3. Validate RCA
    assert rca.incident_type == IncidentType.HIGH_ERROR_RATE
    assert rca.confidence >= 0.75
    assert len(rca.evidence_ids) >= 1
    assert rca.requires_human_approval is True
    assert "database" in rca.root_cause.lower() or "timeout" in rca.root_cause.lower()
    assert rca.agent_metrics is not None
    assert rca.agent_metrics.duration_seconds > 0


def test_investigate_crashloop_scenario():
    # 1. Trigger CrashLoop incident
    subprocess.run(["./scripts/trigger-incident.sh", "crashloop"], check=True, capture_output=True)
    time.sleep(4)

    # 2. Run SRE Agent Investigation
    agent = SREAgent(llm_provider=MockRuleBasedLLMProvider())
    rca = agent.investigate(namespace="demo", workload="demo-app")

    # 3. Validate RCA
    assert rca.incident_type == IncidentType.CRASHLOOP_BACKOFF
    assert rca.confidence >= 0.75
    assert len(rca.evidence_ids) >= 1
    assert rca.requires_human_approval is True
    assert "panic" in rca.root_cause.lower() or "exit code 1" in rca.root_cause.lower() or "fatal" in rca.root_cause.lower()


def test_investigate_resource_exhaustion_scenario():
    # 1. Trigger Resource Exhaustion incident
    subprocess.run(["./scripts/trigger-incident.sh", "resource-exhaustion"], check=True, capture_output=True)
    time.sleep(12)  # Wait for memory leak to exceed 128Mi limit and trigger OOMKilled

    # 2. Run SRE Agent Investigation
    agent = SREAgent(llm_provider=MockRuleBasedLLMProvider())
    rca = agent.investigate(namespace="demo", workload="demo-app")

    # 3. Validate RCA
    assert rca.incident_type == IncidentType.RESOURCE_EXHAUSTION
    assert rca.confidence >= 0.75
    assert len(rca.evidence_ids) >= 1
    assert rca.requires_human_approval is True
    assert "oom" in rca.root_cause.lower() or "memory" in rca.root_cause.lower()
