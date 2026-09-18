from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

RemediationStatus = Literal["SUCCESS", "FAILED", "BLOCKED", "DRY_RUN", "VERIFICATION_TIMEOUT"]


class PreRemediationSnapshot(BaseModel):
    """
    Workload state captured immediately prior to remediation mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_name: str
    namespace: str
    desired_replicas: int
    available_replicas: int
    ready_replicas: int
    pod_count: int
    pod_restarts: Dict[str, int] = Field(default_factory=dict)
    container_statuses: Dict[str, str] = Field(default_factory=dict)
    current_image: Optional[str] = None
    current_revision: Optional[str] = None
    captured_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RemediationVerification(BaseModel):
    """
    Post-remediation workload verification telemetry and health status.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    healthy: bool
    checks: List[str] = Field(default_factory=list)
    failed_checks: List[str] = Field(default_factory=list)
    observations: Dict[str, Any] = Field(default_factory=dict)
    verified_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RemediationResult(BaseModel):
    """
    Immutable audit and outcome model for a controlled remediation execution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str = Field(..., pattern=r"^exec-[a-zA-Z0-9_-]+$")
    request_id: str
    approval_id: Optional[str] = None
    action: str
    target: Dict[str, Any]
    status: RemediationStatus
    pre_snapshot: Optional[PreRemediationSnapshot] = None
    post_verification: Optional[RemediationVerification] = None
    started_at: str
    completed_at: str
    error: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class RemediationMetricsTracker:
    """
    In-memory metrics tracker for remediation actions, approvals, and outcomes.
    """

    def __init__(self):
        self.requests_total: int = 0
        self.approved_total: int = 0
        self.denied_total: int = 0
        self.success_total: int = 0
        self.failed_total: int = 0
        self.verification_failures_total: int = 0
        self.action_counts: Dict[str, int] = {"restart": 0, "scale": 0, "rollback": 0}
        self.total_duration_seconds: float = 0.0

    def record_execution(self, action: str, status: RemediationStatus, duration: float):
        self.requests_total += 1
        self.total_duration_seconds += duration

        if "restart" in action:
            self.action_counts["restart"] += 1
        elif "scale" in action:
            self.action_counts["scale"] += 1
        elif "rollback" in action:
            self.action_counts["rollback"] += 1

        if status == "SUCCESS":
            self.success_total += 1
        elif status == "FAILED" or status == "VERIFICATION_TIMEOUT":
            self.failed_total += 1
            self.verification_failures_total += 1
        elif status == "BLOCKED":
            self.denied_total += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "remediation_requests_total": self.requests_total,
            "remediation_approved_total": self.approved_total,
            "remediation_denied_total": self.denied_total,
            "remediation_success_total": self.success_total,
            "remediation_failed_total": self.failed_total,
            "remediation_verification_failures_total": self.verification_failures_total,
            "action_counts": dict(self.action_counts),
            "average_duration_seconds": round(self.total_duration_seconds / max(self.requests_total, 1), 4),
        }
