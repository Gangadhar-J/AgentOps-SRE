from datetime import datetime, timezone
from typing import List, Literal
from pydantic import BaseModel, ConfigDict, Field


class PolicyDecision(BaseModel):
    """
    Immutable authorization decision produced deterministically by the PolicyEngine.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(
        ...,
        pattern=r"^dec-[a-zA-Z0-9_-]+$",
        description="Unique decision correlation identifier",
    )
    decision: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"] = Field(
        ...,
        description="Authorization evaluation outcome",
    )
    reason: str = Field(
        ...,
        description="Deterministic justification for the policy decision",
    )
    matched_policies: List[str] = Field(
        default_factory=list,
        description="List of policy IDs evaluated during decision making",
    )
    violated_constraints: List[str] = Field(
        default_factory=list,
        description="List of specific constraint violations if decision is DENY",
    )
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(
        default="MEDIUM",
        description="Assigned risk classification from policy rules (never from agent)",
    )
    required_approval: bool = Field(
        default=False,
        description="Whether human authorization is mandatory prior to execution",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of decision",
    )

    @property
    def is_allowed(self) -> bool:
        return self.decision == "ALLOW"

    @property
    def is_denied(self) -> bool:
        return self.decision == "DENY"

    @property
    def is_approval_required(self) -> bool:
        return self.decision == "REQUIRE_APPROVAL"
