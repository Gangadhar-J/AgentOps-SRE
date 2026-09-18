import pytest
from agentops.clients.remediation import KubernetesRemediationClient
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
)


def test_live_restart_deployment_through_gateway():
    gateway = SecurityGateway()
    manager = gateway.approval_manager
    engine = gateway.policy_engine

    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.5.0")
    cap = Capability(
        name="k8s.remediation.restart_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"]),
    )
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id="req-live-restart-1")
    req = ActionRequest(
        request_id="req-live-restart-1",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Live cluster rolling restart verification",
        evidence_refs=["E001"],
    )

    # 1. Create approval request
    dec = engine.evaluate(sec_ctx, req)
    app = manager.create_approval(req, dec)

    # 2. Operator approves
    op = OperatorIdentity(operator_id="alice.sre", display_name="Alice SRE")
    manager.approve(app.approval_id, operator=op)

    # 3. Execute approved remediation on live cluster
    result = gateway.execute_remediation(
        security_context=sec_ctx,
        action_request=req,
        approval_id=app.approval_id,
        timeout_seconds=60,
    )

    assert result.status == "SUCCESS"
    assert result.pre_snapshot is not None
    assert result.post_verification is not None
    assert result.post_verification.healthy is True
    assert result.post_verification.observations["available_replicas"] >= 1


def test_live_scale_deployment_through_gateway():
    gateway = SecurityGateway()
    manager = gateway.approval_manager
    engine = gateway.policy_engine

    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.5.0")
    cap = Capability(
        name="k8s.remediation.scale_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"], max_replicas=4),
    )
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id="req-live-scale-1")
    req = ActionRequest(
        request_id="req-live-scale-1",
        action="k8s.remediation.scale_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app", parameters={"replicas": 3}),
        reason="Live cluster scale out to 3 replicas",
        evidence_refs=["E001", "E002"],
    )

    # 1. Create and approve
    dec = engine.evaluate(sec_ctx, req)
    app = manager.create_approval(req, dec)
    op = OperatorIdentity(operator_id="alice.sre", display_name="Alice SRE")
    manager.approve(app.approval_id, operator=op)

    # 2. Execute scale to 3
    result = gateway.execute_remediation(
        security_context=sec_ctx,
        action_request=req,
        approval_id=app.approval_id,
        timeout_seconds=60,
    )
    assert result.status == "SUCCESS"
    assert result.post_verification.observations["ready_replicas"] == 3

    # 3. Clean up: scale back to 2 replicas
    cleanup_req = ActionRequest(
        request_id="req-live-scale-cleanup",
        action="k8s.remediation.scale_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app", parameters={"replicas": 2}),
        reason="Scale back to default 2 replicas",
        evidence_refs=["E001"],
    )
    cleanup_app = manager.create_approval(cleanup_req, engine.evaluate(sec_ctx, cleanup_req))
    manager.approve(cleanup_app.approval_id, operator=op)
    cleanup_res = gateway.execute_remediation(
        security_context=sec_ctx,
        action_request=cleanup_req,
        approval_id=cleanup_app.approval_id,
        timeout_seconds=60,
    )
    assert cleanup_res.status == "SUCCESS"
    assert cleanup_res.post_verification.observations["ready_replicas"] == 2


def test_scale_out_of_bounds_blocked_by_gateway():
    gateway = SecurityGateway()
    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.5.0")
    cap = Capability(
        name="k8s.remediation.scale_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"], max_replicas=3),
    )
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id="req-live-scale-blocked")
    # Attempting to scale to 10 replicas when max_replicas is 3
    req = ActionRequest(
        request_id="req-live-scale-blocked",
        action="k8s.remediation.scale_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app", parameters={"replicas": 10}),
        reason="Scale out beyond authorized bounds",
        evidence_refs=["E001"],
    )

    result = gateway.execute_remediation(
        security_context=sec_ctx,
        action_request=req,
        approval_id=None,
    )
    assert result.status == "BLOCKED"
    assert "remediation requires human approval" in result.error.lower() or "denied" in result.error.lower()
