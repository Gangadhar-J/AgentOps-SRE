from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("agentops.security.audit")


class PolicyEvaluationRecord(BaseModel):
    """
    Structured, tamper-resistant audit record capturing every policy evaluation.
    Contains zero sensitive tokens or credentials.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(..., description="Decision identifier")
    request_id: str = Field(..., description="ActionRequest identifier")
    agent_id: str = Field(..., description="Agent identity identifier")
    action: str = Field(..., description="Action capability identifier")
    target: Dict[str, Any] = Field(..., description="Structured action target")
    risk_level: str = Field(..., description="Assigned risk level")
    decision: str = Field(..., description="ALLOW, DENY, or REQUIRE_APPROVAL")
    matched_policies: List[str] = Field(default_factory=list)
    violated_constraints: List[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AuditLogger:
    """
    In-memory and structured file audit recorder for Policy Engine evaluations.
    """

    def __init__(self, max_records: int = 1000):
        self._records: List[PolicyEvaluationRecord] = []
        self._max_records = max_records

    def record(self, record: PolicyEvaluationRecord) -> None:
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records.pop(0)

        # Structured log entry
        logger.info(
            f"[AUDIT] decision={record.decision} id={record.decision_id} "
            f"agent={record.agent_id} action={record.action} risk={record.risk_level}"
        )

    def get_records(self) -> List[PolicyEvaluationRecord]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()
