from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

IncidentSource = Literal["MANUAL", "ALERT", "DEMO"]


class LLMRuntime(BaseModel):
    """Execution telemetry and details for the LLM that analyzed the incident."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    mode: str = Field(..., description="e.g. local, cloud, rule-engine")
    latency_seconds: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    tokens_per_second: Optional[float] = None
    status: str = "READY"


class EvidenceDetail(BaseModel):
    """Structured evidence item exposed to operators."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source: str
    resource: str
    metric_or_query: str
    observation: str
    severity: str = "INFO"


class IncidentReport(BaseModel):
    """
    High-level, decision-oriented incident summary for SRE operators.
    Exposes RCA, telemetry evidence counts, and security approval state
    without raw internal plumbing complexity.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: str
    namespace: str
    workload: str
    status: str = Field(..., description="e.g. ACTIVE, INVESTIGATED, PENDING_APPROVAL, RESOLVED")
    source: IncidentSource = "MANUAL"
    incident_type: str
    confidence: float
    summary: str
    root_cause: str
    llm_runtime: Optional[LLMRuntime] = None

    # Structured evidence counts & items
    evidence_summary: Dict[str, int] = Field(
        default_factory=lambda: {"kubernetes": 0, "prometheus": 0, "loki": 0, "total": 0}
    )
    evidence_items: List[EvidenceDetail] = Field(default_factory=list)

    # Remediation & Policy information
    recommended_remediation: Optional[str] = None
    recommended_action: Optional[str] = None
    risk_level: Optional[str] = None
    policy_decision: Optional[str] = None
    policy_reason: Optional[str] = None
    approval_required: bool = False
    approval_id: Optional[str] = None
    action_request_id: Optional[str] = None

    duration_seconds: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RemediationExecutionSummary(BaseModel):
    """
    Outcome summary of an authorized, executed remediation.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    approval_id: Optional[str] = None
    action: str
    target: Dict[str, Any]
    authorization_status: str
    mutation_status: str
    rollout_status: str
    ready_replicas: Optional[int] = None
    desired_replicas: Optional[int] = None
    resolution_status: str
    verification_result: Optional[Dict[str, Any]] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    executed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
