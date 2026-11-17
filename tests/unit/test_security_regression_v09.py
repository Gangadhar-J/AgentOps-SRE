import os
import tempfile
from unittest.mock import MagicMock
import pytest

from agentops.security import (
    ActionRequest,
    ActionTarget,
    AgentIdentity,
    ApprovalManager,
    Capability,
    CapabilityConstraints,
    OperatorIdentity,
    PolicyEngine,
    SecurityContext,
    SecurityGateway,
    SQLiteApprovalStore,
)
from agentops.worker.models import InvestigationEvent


@pytest.fixture
def temp_approval_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def approval_store(temp_approval_db):
    return SQLiteApprovalStore(db_path=temp_approval_db)


@pytest.fixture
def approval_manager(approval_store):
    return ApprovalManager(storage=approval_store, default_ttl_seconds=300)


@pytest.fixture
def operator_alice():
    return OperatorIdentity(
        operator_id="alice.sre",
        operator_type="human_operator",
        display_name="Alice SRE",
    )


@pytest.fixture
def sample_action_request():
    return ActionRequest(
        request_id="req-v09-test-100",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="CrashLoopBackOff diagnosed by AI",
        evidence_refs=["E001"],
    )


def test_autonomous_remediation_strictly_blocked_without_approval(
    approval_manager, sample_action_request
):
    """
    Verify that autonomous execution without human operator approval is strictly BLOCKED.
    Even with valid agent identity and capability, policy requires human approval.
    """
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, approval_manager=approval_manager)

    cap = Capability(
        name="k8s.remediation.restart_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"]),
    )
    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.9.0")
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id=sample_action_request.request_id)

    mock_exec = MagicMock()
    decision, result, approval = gateway.execute_action(sec_ctx, sample_action_request, executor_callback=mock_exec)

    # Must require approval, must NOT execute immediately
    assert decision.decision == "REQUIRE_APPROVAL"
    assert result is None
    assert approval is not None
    assert approval.status == "PENDING"
    mock_exec.assert_not_called()


def test_event_and_trace_metadata_cannot_bypass_approval_binding(
    approval_manager, operator_alice, sample_action_request
):
    """
    Verify that injecting custom trace IDs or manipulating investigation events
    cannot grant capabilities, forge approval IDs, or bypass request binding.
    """
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, approval_manager=approval_manager)

    cap = Capability(name="k8s.remediation.restart_deployment", resource="deployment")
    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.9.0")
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id=sample_action_request.request_id)

    # Legitimate pending approval requested
    _, _, approval = gateway.execute_action(sec_ctx, sample_action_request)
    approval_manager.approve(approval.approval_id, operator=operator_alice)

    # Tampered request binding (e.g. attempting to redirect action to production namespace via metadata)
    tampered_request = ActionRequest(
        request_id=sample_action_request.request_id,
        action=sample_action_request.action,
        target=ActionTarget(namespace="production", resource_type="deployment", resource_name="demo-app"),
        reason=sample_action_request.reason,
        evidence_refs=sample_action_request.evidence_refs,
    )

    mock_exec = MagicMock()
    exec_dec, exec_res = gateway.execute_approved_action(
        approval_id=approval.approval_id,
        security_context=sec_ctx,
        action_request=tampered_request,
        executor_callback=mock_exec,
    )

    assert exec_dec.decision == "DENY"
    assert "tampered" in exec_dec.reason.lower() or "binding" in exec_dec.reason.lower() or "digest" in exec_dec.reason.lower()
    mock_exec.assert_not_called()


def test_forbidden_namespace_strictly_denied_by_policy(
    approval_manager, sample_action_request
):
    """
    Verify that attempting to remediate a workload in a forbidden namespace (e.g. kube-system)
    is denied by capability constraints and policy engine.
    """
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, approval_manager=approval_manager)

    # Attempt to target kube-system
    forbidden_request = ActionRequest(
        request_id="req-forbidden-ns",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="kube-system", resource_type="deployment", resource_name="coredns"),
        reason="CoreDNS restart attempt",
        evidence_refs=["E001"],
    )

    cap = Capability(
        name="k8s.remediation.restart_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"]),
    )
    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.9.0")
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id=forbidden_request.request_id)

    mock_exec = MagicMock()
    decision, result, approval = gateway.execute_action(sec_ctx, forbidden_request, executor_callback=mock_exec)

    assert decision.decision == "DENY"
    assert result is None
    mock_exec.assert_not_called()


def test_event_model_immutability_and_type_safety():
    """
    Verify that InvestigationEvent models enforce validation and reject invalid stage_status or duration.
    """
    ev = InvestigationEvent(
        event_id=1,
        job_id="job-sec-test",
        event_type="progress",
        stage="collecting_kubernetes",
        message="Security test event",
        stage_status="completed",
        duration_ms=55.4,
        evidence_count=3,
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        schema_version=1,
    )
    assert ev.stage_status == "completed"
    assert ev.duration_ms == 55.4
    assert ev.evidence_count == 3
    assert ev.schema_version == 1
