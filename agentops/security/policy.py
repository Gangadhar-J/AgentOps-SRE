import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional
import uuid
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from agentops.config import settings
from agentops.security.capabilities import CAPABILITY_PATTERN, CapabilityConstraints
from agentops.security.context import SecurityContext
from agentops.security.decision import PolicyDecision
from agentops.security.requests import ActionRequest

logger = logging.getLogger("agentops.security.policy")


class PolicyRule(BaseModel):
    """
    Declarative policy rule specifying authorization conditions, risk, and decision outcome.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: Optional[str] = None
    agent_ids: Optional[List[str]] = Field(default=None, description="Permitted agent IDs (None = all agents)")
    action: str = Field(..., description="Target capability name (<domain>.<operation>.<resource>)")
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    decision: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"] = "DENY"
    requires_evidence: bool = Field(default=False, description="Whether ActionRequest must cite evidence references")
    constraints: Optional[CapabilityConstraints] = None

    @field_validator("action")
    @classmethod
    def validate_action_taxonomy(cls, value: str) -> str:
        trimmed = value.strip().lower()
        if "*" in trimmed or trimmed in ("admin", "root", "k8s.admin", "all"):
            raise ValueError(f"Wildcard policy action '{value}' is strictly prohibited")
        if not CAPABILITY_PATTERN.match(trimmed):
            raise ValueError(f"Policy action '{value}' must adhere to '<domain>.<operation>.<resource>' format")
        return trimmed


class PolicySet(BaseModel):
    """
    Validated collection of declarative policy rules.
    """

    policies: List[PolicyRule] = Field(default_factory=list)

    @classmethod
    def load_from_yaml(cls, filepath: str) -> "PolicySet":
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Policy configuration file not found at: {filepath}")
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        raw_policies = data.get("policies", [])
        return cls(policies=[PolicyRule(**p) for p in raw_policies])


class PolicyEngine:
    """
    Deterministic authorization engine enforcing default-deny, capability matching,
    constraint evaluation, risk classification, and policy precedence.
    """

    def __init__(
        self,
        policy_set: Optional[PolicySet] = None,
        policy_file: Optional[str] = None,
    ):
        if policy_set:
            self.policy_set = policy_set
        elif policy_file:
            self.policy_set = PolicySet.load_from_yaml(policy_file)
        else:
            default_path = settings.POLICIES_PATH
            if not os.path.exists(default_path):
                # Fallback to current working directory if run from custom root
                alt_path = os.path.join(os.getcwd(), "config", "policies.yaml")
                default_path = alt_path if os.path.exists(alt_path) else default_path

            if os.path.exists(default_path):
                self.policy_set = PolicySet.load_from_yaml(default_path)
            else:
                self.policy_set = PolicySet(policies=[])

    def evaluate(self, security_context: SecurityContext, action_request: ActionRequest) -> PolicyDecision:
        """
        Evaluate an ActionRequest against the SecurityContext and PolicySet.
        
        Precedence:
        1. Explicit DENY (Critical global or targeted deny)
        2. Missing capability / Constraint failure
        3. Evidence check failure
        4. REQUIRE_APPROVAL
        5. ALLOW
        Default: DENY
        """
        dec_id = f"dec-{uuid.uuid4().hex[:8]}"
        action = action_request.action
        target = action_request.target
        agent_id = security_context.identity.agent_id

        # -------------------------------------------------------------
        # Step 1: Capability Matching Check
        # -------------------------------------------------------------
        matching_cap = next((c for c in security_context.capabilities if c.name == action), None)
        if not matching_cap:
            return PolicyDecision(
                decision_id=dec_id,
                decision="DENY",
                reason=f"Agent '{agent_id}' does not possess granted capability for action '{action}'",
                risk_level="HIGH",
                matched_policies=[],
                violated_constraints=[f"missing_capability:{action}"],
                required_approval=False,
            )

        # -------------------------------------------------------------
        # Step 2: Capability Constraints Evaluation
        # -------------------------------------------------------------
        violated_constraints = []
        cap_constraints = matching_cap.constraints
        if cap_constraints:
            if cap_constraints.namespaces and target.namespace not in cap_constraints.namespaces:
                violated_constraints.append(f"capability_namespace_forbidden:{target.namespace}")
            if cap_constraints.allowed_resources and target.resource_name not in cap_constraints.allowed_resources:
                violated_constraints.append(f"capability_resource_forbidden:{target.resource_name}")
            if cap_constraints.max_replicas is not None:
                requested_replicas = target.parameters.get("replicas")
                if requested_replicas and requested_replicas > cap_constraints.max_replicas:
                    violated_constraints.append(
                        f"capability_max_replicas_exceeded:{requested_replicas}>{cap_constraints.max_replicas}"
                    )

        # -------------------------------------------------------------
        # Step 3: Match Policy Rules
        # -------------------------------------------------------------
        matched_rules: List[PolicyRule] = []
        for rule in self.policy_set.policies:
            if rule.action == action:
                if rule.agent_ids is None or agent_id in rule.agent_ids:
                    # Check if rule has namespace constraints
                    if rule.constraints and rule.constraints.namespaces:
                        if target.namespace in rule.constraints.namespaces:
                            matched_rules.append(rule)
                    else:
                        matched_rules.append(rule)

        if not matched_rules:
            return PolicyDecision(
                decision_id=dec_id,
                decision="DENY",
                reason=f"Default Deny: No matching policy rule permitting action '{action}' for agent '{agent_id}'",
                risk_level="HIGH",
                matched_policies=[],
                violated_constraints=violated_constraints,
                required_approval=False,
            )

        matched_policy_ids = [r.id for r in matched_rules]

        # -------------------------------------------------------------
        # Step 4: Check for Explicit DENY (Deny Overrides All)
        # -------------------------------------------------------------
        deny_rules = [r for r in matched_rules if r.decision == "DENY"]
        if deny_rules:
            highest_risk = "CRITICAL" if any(r.risk_level == "CRITICAL" for r in deny_rules) else deny_rules[0].risk_level
            return PolicyDecision(
                decision_id=dec_id,
                decision="DENY",
                reason=f"Action '{action}' explicitly denied by policy rules: {', '.join(r.id for r in deny_rules)}",
                matched_policies=matched_policy_ids,
                violated_constraints=violated_constraints + [f"explicit_deny:{r.id}" for r in deny_rules],
                risk_level=highest_risk,
                required_approval=False,
            )

        # -------------------------------------------------------------
        # Step 5: Check Capability Constraint Violations
        # -------------------------------------------------------------
        if violated_constraints:
            return PolicyDecision(
                decision_id=dec_id,
                decision="DENY",
                reason=f"Action request target violates granted capability constraints: {', '.join(violated_constraints)}",
                matched_policies=matched_policy_ids,
                violated_constraints=violated_constraints,
                risk_level="HIGH",
                required_approval=False,
            )

        # -------------------------------------------------------------
        # Step 6: Check Evidence Requirements
        # -------------------------------------------------------------
        evidence_required_rules = [r for r in matched_rules if r.requires_evidence]
        if evidence_required_rules and not action_request.evidence_refs:
            return PolicyDecision(
                decision_id=dec_id,
                decision="DENY",
                reason=f"Action '{action}' requires supporting investigation evidence, but none was provided",
                matched_policies=matched_policy_ids,
                violated_constraints=["missing_evidence_references"],
                risk_level="HIGH",
                required_approval=False,
            )

        # -------------------------------------------------------------
        # Step 7: Check REQUIRE_APPROVAL vs ALLOW
        # -------------------------------------------------------------
        approval_rules = [r for r in matched_rules if r.decision == "REQUIRE_APPROVAL"]
        if approval_rules:
            selected_rule = approval_rules[0]
            return PolicyDecision(
                decision_id=dec_id,
                decision="REQUIRE_APPROVAL",
                reason=f"Action '{action}' requires human authorization per policy '{selected_rule.id}'",
                matched_policies=matched_policy_ids,
                violated_constraints=[],
                risk_level=selected_rule.risk_level,
                required_approval=True,
            )

        allow_rules = [r for r in matched_rules if r.decision == "ALLOW"]
        if allow_rules:
            selected_rule = allow_rules[0]
            return PolicyDecision(
                decision_id=dec_id,
                decision="ALLOW",
                reason=f"Action '{action}' authorized by policy '{selected_rule.id}'",
                matched_policies=matched_policy_ids,
                violated_constraints=[],
                risk_level=selected_rule.risk_level,
                required_approval=False,
            )

        # Default Deny fallback
        return PolicyDecision(
            decision_id=dec_id,
            decision="DENY",
            reason=f"Default Deny: Policy evaluation concluded without explicit authorization for action '{action}'",
            matched_policies=matched_policy_ids,
            violated_constraints=violated_constraints,
            risk_level="HIGH",
            required_approval=False,
        )
