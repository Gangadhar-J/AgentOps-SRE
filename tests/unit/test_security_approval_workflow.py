from datetime import datetime, timezone, timedelta
import os
import tempfile
import time
from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError
from agentops.security import (
    ActionRequest,
    ActionTarget,
    AgentIdentity,
    ApprovalManager,
    ApprovalRecord,
    ApprovalRequest,
    Capability,
    CapabilityConstraints,
    OperatorIdentity,
    PolicyDecision,
    PolicyEngine,
    PolicyRule,
    PolicySet,
    SecurityContext,
    SecurityGateway,
    SQLiteApprovalStore,
)


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def test_store(temp_db_path):
    return SQLiteApprovalStore(db_path=temp_db_path)


@pytest.fixture
def test_manager(test_store):
    return ApprovalManager(storage=test_store, default_ttl_seconds=300)


@pytest.fixture
def test_operator():
    return OperatorIdentity(
        operator_id="alice.sre",
        operator_type="human_operator",
        display_name="Alice SRE",
    )


@pytest.fixture
def sample_action_request():
    return ActionRequest(
        request_id="req-test-100",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Workload demo-app entered CrashLoopBackOff due to unhandled panic",
        evidence_refs=["E001", "E004"],
    )


@pytest.fixture
def sample_policy_decision():
    return PolicyDecision(
        decision_id="dec-test-100",
        decision="REQUIRE_APPROVAL",
        reason="Action requires human authorization per policy 'restart-deployment-requires-approval'",
        matched_policies=["restart-deployment-requires-approval"],
        risk_level="MEDIUM",
        required_approval=True,
    )


# =============================================================
# 1. State Machine Tests
# =============================================================
def test_approval_state_machine_transitions(test_manager, test_operator, sample_action_request, sample_policy_decision):
    # 1. Create -> PENDING
    app = test_manager.create_approval(sample_action_request, sample_policy_decision)
    assert app.status == "PENDING"
    assert app.decided_by is None

    # 2. PENDING -> APPROVED
    approved = test_manager.approve(app.approval_id, operator=test_operator, reason="Looks safe to restart")
    assert approved.status == "APPROVED"
    assert approved.decided_by == "alice.sre"
    assert approved.decision_reason == "Looks safe to restart"

    # 3. APPROVED cannot transition to REJECTED or APPROVED again
    with pytest.raises(ValueError, match="Only 'PENDING' requests may be approved"):
        test_manager.approve(app.approval_id, operator=test_operator)

    with pytest.raises(ValueError, match="Only 'PENDING' requests may be rejected"):
        test_manager.reject(app.approval_id, operator=test_operator)


def test_approval_rejection_transition(test_manager, test_operator, sample_action_request, sample_policy_decision):
    app = test_manager.create_approval(sample_action_request, sample_policy_decision)
    rejected = test_manager.reject(app.approval_id, operator=test_operator, reason="Incorrect root cause identified")
    assert rejected.status == "REJECTED"
    assert rejected.decided_by == "alice.sre"

    # REJECTED cannot transition to APPROVED
    with pytest.raises(ValueError, match="Only 'PENDING' requests may be approved"):
        test_manager.approve(app.approval_id, operator=test_operator)


# =============================================================
# 2. Expiration Tests
# =============================================================
def test_approval_expiration_logic(test_manager, test_operator, sample_action_request, sample_policy_decision):
    # Create approval with 1-second TTL
    app = test_manager.create_approval(sample_action_request, sample_policy_decision, ttl_seconds=1)
    time.sleep(1.2)

    # Retrieval should dynamically mark it EXPIRED
    fetched = test_manager.get_approval(app.approval_id)
    assert fetched.status == "EXPIRED"
    assert fetched.is_expired() is True

    # Cannot approve expired request
    with pytest.raises(ValueError, match="Only 'PENDING' requests may be approved"):
        test_manager.approve(app.approval_id, operator=test_operator)


# =============================================================
# 3. Replay Protection & Consumption
# =============================================================
def test_approval_consumption_single_use(test_manager, test_operator, sample_action_request, sample_policy_decision):
    app = test_manager.create_approval(sample_action_request, sample_policy_decision)
    test_manager.approve(app.approval_id, operator=test_operator)

    # 1st consume succeeds (APPROVED -> CONSUMED)
    consumed = test_manager.consume(app.approval_id)
    assert consumed.status == "CONSUMED"
    assert consumed.consumed_at is not None

    # 2nd consume attempt fails
    with pytest.raises(ValueError, match="Cannot consume approval with status 'CONSUMED'"):
        test_manager.consume(app.approval_id)


# =============================================================
# 4. Gateway Integration & Request Binding Verification
# =============================================================
def test_gateway_require_approval_creates_request(test_manager, sample_action_request):
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, approval_manager=test_manager)

    cap = Capability(
        name="k8s.remediation.restart_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"]),
    )
    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.4.4")
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id=sample_action_request.request_id)

    mock_exec = MagicMock()
    decision, result, approval = gateway.execute_action(sec_ctx, sample_action_request, executor_callback=mock_exec)

    assert decision.decision == "REQUIRE_APPROVAL"
    assert result is None
    assert approval is not None
    assert approval.status == "PENDING"
    mock_exec.assert_not_called()


def test_gateway_executes_approved_action_safely(test_manager, test_operator, sample_action_request):
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, approval_manager=test_manager)

    cap = Capability(
        name="k8s.remediation.restart_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"]),
    )
    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.4.4")
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id=sample_action_request.request_id)

    # 1. Trigger REQUIRE_APPROVAL
    _, _, approval = gateway.execute_action(sec_ctx, sample_action_request)
    assert approval is not None

    # 2. Human Operator approves
    test_manager.approve(approval.approval_id, operator=test_operator, reason="Approved by SRE oncall")

    # 3. Execute approved action via gateway
    mock_exec = MagicMock(return_value={"status": "mock_remediation_success"})
    exec_dec, exec_res = gateway.execute_approved_action(
        approval_id=approval.approval_id,
        security_context=sec_ctx,
        action_request=sample_action_request,
        executor_callback=mock_exec,
    )

    assert exec_dec.decision == "ALLOW"
    assert exec_res == {"status": "mock_remediation_success"}
    mock_exec.assert_called_once()

    # 4. Replay attempt with consumed approval fails
    mock_exec.reset_mock()
    replay_dec, replay_res = gateway.execute_approved_action(
        approval_id=approval.approval_id,
        security_context=sec_ctx,
        action_request=sample_action_request,
        executor_callback=mock_exec,
    )
    assert replay_dec.decision == "DENY"
    assert "already been consumed" in replay_dec.reason
    mock_exec.assert_not_called()


def test_gateway_rejects_tampered_request_binding(test_manager, test_operator, sample_action_request):
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, approval_manager=test_manager)

    cap = Capability(name="k8s.remediation.restart_deployment", resource="deployment")
    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.4.4")
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id=sample_action_request.request_id)

    _, _, approval = gateway.execute_action(sec_ctx, sample_action_request)
    test_manager.approve(approval.approval_id, operator=test_operator)

    # Tampered request: Target namespace changed to 'production'
    tampered_request = ActionRequest(
        request_id=sample_action_request.request_id,
        action=sample_action_request.action,
        target=ActionTarget(namespace="production", resource_type="deployment", resource_name="demo-app"),
        reason=sample_action_request.reason,
        evidence_refs=sample_action_request.evidence_refs,
    )

    mock_exec = MagicMock()
    dec, res = gateway.execute_approved_action(
        approval_id=approval.approval_id,
        security_context=sec_ctx,
        action_request=tampered_request,
        executor_callback=mock_exec,
    )
    assert dec.decision == "DENY"
    assert "binding" in dec.reason.lower()
    mock_exec.assert_not_called()


# =============================================================
# 5. Persistence Tests (SQLite)
# =============================================================
def test_approvals_persist_across_store_instances(temp_db_path, test_operator, sample_action_request, sample_policy_decision):
    # Store instance 1: create and approve
    store1 = SQLiteApprovalStore(db_path=temp_db_path)
    mgr1 = ApprovalManager(storage=store1)
    app = mgr1.create_approval(sample_action_request, sample_policy_decision)
    mgr1.approve(app.approval_id, operator=test_operator, reason="Persisted approval")

    # Store instance 2: new process reading database
    store2 = SQLiteApprovalStore(db_path=temp_db_path)
    mgr2 = ApprovalManager(storage=store2)
    restored = mgr2.get_approval(app.approval_id)

    assert restored is not None
    assert restored.approval_id == app.approval_id
    assert restored.status == "APPROVED"
    assert restored.decided_by == "alice.sre"
    assert restored.decision_reason == "Persisted approval"

    # Audit records survive
    audit_records = store2.list_audit_records(approval_id=app.approval_id)
    assert len(audit_records) >= 1
    assert audit_records[0].operator_id == "alice.sre"
    assert audit_records[0].decision == "APPROVE"
