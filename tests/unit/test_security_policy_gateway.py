from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError
from agentops.security import (
    ActionRequest,
    ActionTarget,
    AgentIdentity,
    AuditLogger,
    Capability,
    CapabilityConstraints,
    PolicyDecision,
    PolicyEngine,
    PolicyEvaluationRecord,
    PolicyRule,
    PolicySet,
    SecurityContext,
    SecurityGateway,
)


@pytest.fixture
def sre_identity():
    return AgentIdentity(
        agent_id="sre-agent-primary",
        agent_type="ai_agent",
        version="0.4.3",
    )


@pytest.fixture
def standard_policy_engine():
    return PolicyEngine(policy_file="config/policies.yaml")


# =============================================================
# 1. Capability & Constraint Tests
# =============================================================
def test_policy_engine_allows_read_with_matching_capability(sre_identity, standard_policy_engine):
    cap = Capability(
        name="k8s.read.pods",
        resource="pod",
        constraints=CapabilityConstraints(namespaces=["demo"]),
    )
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(cap,), request_id="req-001")
    req = ActionRequest(
        request_id="req-001",
        action="k8s.read.pods",
        target=ActionTarget(namespace="demo", resource_type="pod", resource_name="demo-app-xxx"),
        reason="Routine pod state inspection",
        evidence_refs=["E001"],
    )

    decision = standard_policy_engine.evaluate(sec_ctx, req)
    assert decision.decision == "ALLOW"
    assert decision.is_allowed is True
    assert decision.risk_level == "LOW"
    assert "allow-k8s-read-pods" in decision.matched_policies


def test_policy_engine_denies_when_capability_missing(sre_identity, standard_policy_engine):
    # Agent has no granted capabilities
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(), request_id="req-002")
    req = ActionRequest(
        request_id="req-002",
        action="k8s.read.pods",
        target=ActionTarget(namespace="demo", resource_type="pod", resource_name="demo-app-xxx"),
        reason="Routine pod state inspection",
        evidence_refs=["E001"],
    )

    decision = standard_policy_engine.evaluate(sec_ctx, req)
    assert decision.decision == "DENY"
    assert "missing_capability:k8s.read.pods" in decision.violated_constraints


def test_policy_engine_denies_on_capability_namespace_constraint(sre_identity, standard_policy_engine):
    # Granted capability is constrained strictly to 'demo' namespace
    cap = Capability(
        name="k8s.read.pods",
        resource="pod",
        constraints=CapabilityConstraints(namespaces=["demo"]),
    )
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(cap,), request_id="req-003")
    # Action requested on 'production' namespace
    req = ActionRequest(
        request_id="req-003",
        action="k8s.read.pods",
        target=ActionTarget(namespace="production", resource_type="pod", resource_name="demo-app-xxx"),
        reason="Inspecting pod in forbidden namespace",
        evidence_refs=["E001"],
    )

    decision = standard_policy_engine.evaluate(sec_ctx, req)
    assert decision.decision == "DENY"
    assert any("capability_namespace_forbidden" in c for c in decision.violated_constraints)


def test_policy_engine_denies_on_max_replicas_exceeded(sre_identity):
    cap = Capability(
        name="k8s.remediation.scale_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], max_replicas=3),
    )
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(cap,), request_id="req-004")
    # Request exceeds max_replicas (requested 10, max 3)
    req = ActionRequest(
        request_id="req-004",
        action="k8s.remediation.scale_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app", parameters={"replicas": 10}),
        reason="Scale out deployment to handle load spike",
        evidence_refs=["E001", "E002"],
    )

    engine = PolicyEngine(policy_file="config/policies.yaml")
    decision = engine.evaluate(sec_ctx, req)
    assert decision.decision == "DENY"
    assert any("capability_max_replicas_exceeded" in c for c in decision.violated_constraints)


# =============================================================
# 2. Remediation & Approval Policy Tests
# =============================================================
def test_policy_engine_requires_approval_for_restart(sre_identity, standard_policy_engine):
    cap = Capability(
        name="k8s.remediation.restart_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"]),
    )
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(cap,), request_id="req-005")
    req = ActionRequest(
        request_id="req-005",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Workload demo-app entered CrashLoopBackOff with fatal panic logs",
        evidence_refs=["E001", "E004"],
    )

    decision = standard_policy_engine.evaluate(sec_ctx, req)
    assert decision.decision == "REQUIRE_APPROVAL"
    assert decision.is_approval_required is True
    assert decision.required_approval is True
    assert decision.risk_level == "MEDIUM"
    assert "restart-deployment-requires-approval" in decision.matched_policies


# =============================================================
# 3. Explicit Deny & Precedence Tests
# =============================================================
def test_explicit_deny_overrides_allow(sre_identity):
    # Setup custom policy set with conflicting ALLOW and DENY
    policies = PolicySet(policies=[
        PolicyRule(
            id="allow-restart-all",
            action="k8s.remediation.restart_deployment",
            risk_level="LOW",
            decision="ALLOW",
        ),
        PolicyRule(
            id="deny-restart-critical",
            action="k8s.remediation.restart_deployment",
            risk_level="CRITICAL",
            decision="DENY",
        ),
    ])
    engine = PolicyEngine(policy_set=policies)

    cap = Capability(name="k8s.remediation.restart_deployment", resource="deployment")
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(cap,), request_id="req-006")
    req = ActionRequest(
        request_id="req-006",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Restart deployment following crash",
        evidence_refs=["E001"],
    )

    decision = engine.evaluate(sec_ctx, req)
    assert decision.decision == "DENY"
    assert decision.risk_level == "CRITICAL"
    assert "deny-restart-critical" in decision.matched_policies


def test_default_deny_when_no_policy_matches(sre_identity):
    engine = PolicyEngine(policy_set=PolicySet(policies=[]))
    cap = Capability(name="k8s.read.pods", resource="pod")
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(cap,), request_id="req-007")
    req = ActionRequest(
        request_id="req-007",
        action="k8s.read.pods",
        target=ActionTarget(namespace="demo", resource_type="pod", resource_name="demo-app-xxx"),
        reason="Read pod status",
        evidence_refs=["E001"],
    )

    decision = engine.evaluate(sec_ctx, req)
    assert decision.decision == "DENY"
    assert "Default Deny" in decision.reason


# =============================================================
# 4. Security Gateway Execution Tests
# =============================================================
def test_gateway_executes_allowed_action(sre_identity, standard_policy_engine):
    audit_logger = AuditLogger()
    gateway = SecurityGateway(policy_engine=standard_policy_engine, audit_logger=audit_logger)

    cap = Capability(name="k8s.read.pods", resource="pod")
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(cap,), request_id="req-008")
    req = ActionRequest(
        request_id="req-008",
        action="k8s.read.pods",
        target=ActionTarget(namespace="demo", resource_type="pod", resource_name="demo-app-xxx"),
        reason="Routine pod state inspection",
        evidence_refs=["E001"],
    )

    mock_executor = MagicMock(return_value={"status": "success", "pods": []})
    decision, result, approval = gateway.execute_action(sec_ctx, req, executor_callback=mock_executor)

    assert decision.decision == "ALLOW"
    assert result == {"status": "success", "pods": []}
    assert approval is None
    mock_executor.assert_called_once()

    records = audit_logger.get_records()
    assert len(records) == 1
    assert records[0].decision == "ALLOW"
    assert records[0].agent_id == "sre-agent-primary"


def test_gateway_blocks_denied_action(sre_identity, standard_policy_engine):
    audit_logger = AuditLogger()
    gateway = SecurityGateway(policy_engine=standard_policy_engine, audit_logger=audit_logger)

    # Missing capability for deletion
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(), request_id="req-009")
    req = ActionRequest(
        request_id="req-009",
        action="k8s.remediation.delete_resource",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Proposing to delete faulty deployment",
        evidence_refs=["E001"],
    )

    mock_executor = MagicMock()
    decision, result, approval = gateway.execute_action(sec_ctx, req, executor_callback=mock_executor)

    assert decision.decision == "DENY"
    assert result is None
    assert approval is None
    mock_executor.assert_not_called()

    records = audit_logger.get_records()
    assert len(records) == 1
    assert records[0].decision == "DENY"


def test_gateway_blocks_require_approval_action(sre_identity, standard_policy_engine):
    audit_logger = AuditLogger()
    gateway = SecurityGateway(policy_engine=standard_policy_engine, audit_logger=audit_logger)

    cap = Capability(name="k8s.remediation.restart_deployment", resource="deployment")
    sec_ctx = SecurityContext(identity=sre_identity, capabilities=(cap,), request_id="req-010")
    req = ActionRequest(
        request_id="req-010",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Restart deployment due to CrashLoopBackOff",
        evidence_refs=["E001", "E004"],
    )

    mock_executor = MagicMock()
    decision, result, approval = gateway.execute_action(sec_ctx, req, executor_callback=mock_executor)

    assert decision.decision == "REQUIRE_APPROVAL"
    assert result is None
    assert approval is not None
    assert approval.status == "PENDING"
    mock_executor.assert_not_called()

    records = audit_logger.get_records()
    assert len(records) == 1
    assert records[0].decision == "REQUIRE_APPROVAL"
