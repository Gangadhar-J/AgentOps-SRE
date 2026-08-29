from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# Evidence reference ID format: E001, E002, E100...
EVIDENCE_ID_PATTERN = re.compile(r"^E\d{3,}$")

# Prohibit raw shell syntax in reasons
PROHIBITED_COMMAND_PATTERNS = [
    re.compile(r"(;\s*rm\s+|;\s*curl\s+|;\s*bash\s+|;\s*sh\s+|\|\s*bash|\|\s*sh|`.*`|\$\(.*\))", re.IGNORECASE),
]


class ActionTarget(BaseModel):
    """
    Structured target resource specification for an ActionRequest.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: str = Field(default="demo", min_length=1, max_length=64, description="Target namespace")
    resource_type: str = Field(..., min_length=2, max_length=64, description="Target resource type (e.g. 'deployment', 'pod')")
    resource_name: str = Field(..., min_length=1, max_length=128, description="Target resource name (e.g. 'demo-app')")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Structured parameters for the action")


class ActionRequest(BaseModel):
    """
    Structured representation of an action proposed by an AI SRE Agent.
    Strictly decoupled from policy authorization decisions (no 'approved' field).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(
        ...,
        pattern=r"^req-[a-zA-Z0-9_-]+$",
        description="Unique request identifier (e.g. 'req-inv-12345')",
    )
    action: str = Field(
        ...,
        description="Target capability identifier (e.g. 'k8s.remediation.restart_deployment')",
    )
    target: ActionTarget = Field(
        ...,
        description="Target resource specification",
    )
    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Evidence-backed rationale for the proposed action",
    )
    evidence_refs: List[str] = Field(
        ...,
        min_length=1,
        description="List of supporting Evidence IDs (e.g. ['E001', 'E004'])",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC request creation timestamp",
    )

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_ids(cls, refs: List[str]) -> List[str]:
        if not refs:
            raise ValueError("ActionRequest must cite at least one supporting evidence reference (e.g. 'E001')")
        for ref in refs:
            if not EVIDENCE_ID_PATTERN.match(ref):
                raise ValueError(f"Invalid evidence reference ID format '{ref}'. Must match 'E001', 'E002', etc.")
        return refs

    @field_validator("reason")
    @classmethod
    def validate_reason_safety(cls, val: str) -> str:
        trimmed = val.strip()
        for pattern in PROHIBITED_COMMAND_PATTERNS:
            if pattern.search(trimmed):
                raise ValueError("ActionRequest reason cannot contain shell commands or command injection sequences")
        return trimmed
