from typing import Any, Dict, List, Optional
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


# Capability naming taxonomy: <domain>.<operation>.<resource>
CAPABILITY_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$")


class CapabilityConstraints(BaseModel):
    """
    Fine-grained constraints limiting where and how a capability may be exercised.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespaces: Optional[List[str]] = Field(
        default=None,
        description="Allowed Kubernetes namespaces (e.g. ['demo', 'staging'])",
    )
    environments: Optional[List[str]] = Field(
        default=None,
        description="Allowed deployment environments (e.g. ['development', 'staging'])",
    )
    max_replicas: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description="Maximum replica count allowed for scale operations",
    )
    allowed_resources: Optional[List[str]] = Field(
        default=None,
        description="Explicit resource names permitted (e.g. ['demo-app'])",
    )


class Capability(BaseModel):
    """
    Immutable representation of an authority/permission granted to an agent.
    A capability is NOT an action request; it represents granted privileges.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        ...,
        description="Standardized capability identifier formatted as <domain>.<operation>.<resource>",
    )
    resource: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Primary resource category (e.g. 'pod', 'deployment', 'event', 'metrics', 'logs')",
    )
    constraints: CapabilityConstraints = Field(
        default_factory=CapabilityConstraints,
        description="Scope constraints governing this capability",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Human-readable explanation of the capability",
    )

    @field_validator("name")
    @classmethod
    def validate_capability_taxonomy(cls, value: str) -> str:
        trimmed = value.strip().lower()

        # Reject wildcard permissions
        if "*" in trimmed or trimmed in ("admin", "root", "k8s.admin", "all"):
            raise ValueError(f"Wildcard or unrestricted capability '{value}' is strictly prohibited")

        # Must conform to <domain>.<operation>.<resource>
        parts = trimmed.split(".")
        if len(parts) != 3 or not CAPABILITY_PATTERN.match(trimmed):
            raise ValueError(
                f"Capability name '{value}' must adhere to '<domain>.<operation>.<resource>' format (e.g. 'k8s.read.pods')"
            )

        domain, operation, resource = parts
        if domain not in ("k8s", "prom", "loki", "system"):
            raise ValueError(f"Unknown capability domain '{domain}'. Must be one of ['k8s', 'prom', 'loki', 'system']")

        if operation not in ("read", "remediation", "investigate", "admin"):
            raise ValueError(f"Unknown operation '{operation}'. Must be one of ['read', 'remediation', 'investigate']")

        return trimmed
