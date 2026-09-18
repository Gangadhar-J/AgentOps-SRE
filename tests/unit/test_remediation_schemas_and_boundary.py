from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError
from agentops.clients.remediation import KubernetesRemediationClient
from agentops.mcp.schemas import (
    K8sRestartDeploymentInput,
    K8sScaleDeploymentInput,
    K8sRollbackDeploymentInput,
)
from agentops.models.remediation import (
    PreRemediationSnapshot,
    RemediationMetricsTracker,
    RemediationResult,
    RemediationVerification,
)
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


# =============================================================
# 1. Schema Validation Tests
# =============================================================
def test_valid_remediation_schemas():
    rst = K8sRestartDeploymentInput(namespace="demo", deployment="demo-app", reason="Crash loop")
    assert rst.namespace == "demo"
    assert rst.deployment == "demo-app"

    scl = K8sScaleDeploymentInput(namespace="demo", deployment="demo-app", replicas=3)
    assert scl.replicas == 3

    rbk = K8sRollbackDeploymentInput(namespace="demo", deployment="demo-app", revision=2)
    assert rbk.revision == 2


def test_remediation_schemas_reject_invalid_bounds():
    # Scale: replicas out of safe bounds (ge=1, le=10)
    with pytest.raises(ValidationError):
        K8sScaleDeploymentInput(namespace="demo", deployment="demo-app", replicas=0)

    with pytest.raises(ValidationError):
        K8sScaleDeploymentInput(namespace="demo", deployment="demo-app", replicas=15)

    # Rollback: negative revision
    with pytest.raises(ValidationError):
        K8sRollbackDeploymentInput(namespace="demo", deployment="demo-app", revision=-1)


# =============================================================
# 2. Client Security Boundary & Reflection Tests
# =============================================================
def test_remediation_client_exposes_no_generic_mutation_methods():
    client = KubernetesRemediationClient()
    prohibited_methods = [
        "delete",
        "delete_pod",
        "delete_namespace",
        "exec",
        "execute_shell",
        "apply",
        "raw_patch",
        "create_secret",
        "update_configmap",
    ]
    for method in prohibited_methods:
        assert not hasattr(client, method), f"Prohibited method '{method}' found on KubernetesRemediationClient"

    # Verify strictly allowed remediation methods
    assert hasattr(client, "restart_deployment")
    assert hasattr(client, "scale_deployment")
    assert hasattr(client, "rollback_deployment")
    assert hasattr(client, "get_workload_snapshot")
    assert hasattr(client, "verify_workload_health")


# =============================================================
# 3. Dry-Run & Gateway Remediation Tests
# =============================================================
def test_gateway_dry_run_does_not_mutate():
    mock_client = MagicMock(spec=KubernetesRemediationClient)
    mock_client.get_workload_snapshot.return_value = PreRemediationSnapshot(
        deployment_name="demo-app",
        namespace="demo",
        desired_replicas=2,
        available_replicas=2,
        ready_replicas=2,
        pod_count=2,
    )
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, remediation_client=mock_client)

    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.5.0")
    cap = Capability(
        name="k8s.remediation.restart_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"]),
    )
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id="req-dry-1")
    req = ActionRequest(
        request_id="req-dry-1",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Testing dry run plan",
        evidence_refs=["E001"],
    )

    result = gateway.execute_remediation(sec_ctx, req, dry_run=True)

    assert result.status == "DRY_RUN"
    assert "WOULD EXECUTE" in result.details.get("plan", "")
    assert result.pre_snapshot is not None
    # Verify mutation methods were NOT called
    mock_client.restart_deployment.assert_not_called()
    mock_client.scale_deployment.assert_not_called()
    mock_client.rollback_deployment.assert_not_called()


def test_gateway_remediation_blocked_without_approval():
    mock_client = MagicMock(spec=KubernetesRemediationClient)
    mock_client.get_workload_snapshot.return_value = PreRemediationSnapshot(
        deployment_name="demo-app",
        namespace="demo",
        desired_replicas=2,
        available_replicas=2,
        ready_replicas=2,
        pod_count=2,
    )
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, remediation_client=mock_client)

    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.5.0")
    cap = Capability(name="k8s.remediation.restart_deployment", resource="deployment")
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id="req-noappr-1")
    req = ActionRequest(
        request_id="req-noappr-1",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Testing blocked unapproved execution",
        evidence_refs=["E001"],
    )

    result = gateway.execute_remediation(sec_ctx, req, approval_id=None)

    assert result.status == "BLOCKED"
    assert result.approval_id is not None
    mock_client.restart_deployment.assert_not_called()


def test_gateway_remediation_executes_with_valid_approval():
    mock_client = MagicMock(spec=KubernetesRemediationClient)
    mock_client.get_workload_snapshot.return_value = PreRemediationSnapshot(
        deployment_name="demo-app",
        namespace="demo",
        desired_replicas=2,
        available_replicas=2,
        ready_replicas=2,
        pod_count=2,
    )
    mock_client.restart_deployment.return_value = {"status": "patched"}
    mock_client.verify_workload_health.return_value = RemediationVerification(
        healthy=True,
        checks=["rollout_complete"],
        observations={"ready_replicas": 2},
    )

    manager = ApprovalManager()
    engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=engine, approval_manager=manager, remediation_client=mock_client)

    identity = AgentIdentity(agent_id="sre-agent-primary", agent_type="ai_agent", version="0.5.0")
    cap = Capability(name="k8s.remediation.restart_deployment", resource="deployment")
    sec_ctx = SecurityContext(identity=identity, capabilities=(cap,), request_id="req-appr-1")
    req = ActionRequest(
        request_id="req-appr-1",
        action="k8s.remediation.restart_deployment",
        target=ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app"),
        reason="Restart deployment due to CrashLoopBackOff",
        evidence_refs=["E001"],
    )

    # 1. Trigger approval requirement
    app = manager.create_approval(req, engine.evaluate(sec_ctx, req))
    # 2. Operator approves
    op = OperatorIdentity(operator_id="alice.sre", display_name="Alice SRE")
    manager.approve(app.approval_id, operator=op)

    # 3. Execute approved remediation
    result = gateway.execute_remediation(sec_ctx, req, approval_id=app.approval_id)

    assert result.status == "SUCCESS"
    assert result.post_verification is not None
    assert result.post_verification.healthy is True
    mock_client.restart_deployment.assert_called_once()
    mock_client.verify_workload_health.assert_called_once()
