from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Dict, List, Literal, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field
from agentops.security.decision import PolicyDecision
from agentops.security.operator import OperatorIdentity
from agentops.security.requests import ActionRequest

logger = logging.getLogger("agentops.security.approval")

ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED", "CONSUMED"]


class ApprovalRequest(BaseModel):
    """
    Immutable representation of an action approval request awaiting human authorization.
    Preserves exact original ActionRequest and PolicyDecision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(..., pattern=r"^appr-[a-zA-Z0-9_-]+$")
    action_request: ActionRequest
    policy_decision: PolicyDecision
    status: ApprovalStatus = "PENDING"
    requested_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    decision_reason: Optional[str] = None
    consumed_at: Optional[str] = None

    def is_expired(self) -> bool:
        try:
            exp_dt = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) >= exp_dt
        except Exception:
            return True


class ApprovalRecord(BaseModel):
    """
    Immutable audit record capturing an operator approval state transition.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str
    request_id: str
    operator_id: Optional[str]
    decision: Literal["APPROVE", "REJECT", "EXPIRE", "CONSUME"]
    previous_status: ApprovalStatus
    new_status: ApprovalStatus
    reason: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ApprovalManager:
    """
    Manages the lifecycle, state transitions, and persistent storage of ApprovalRequests.
    Enforces strict state machine transitions and expiration logic.
    """

    def __init__(self, storage=None, default_ttl_seconds: int = 900):
        if storage is None:
            from agentops.security.storage import SQLiteApprovalStore
            self.storage = SQLiteApprovalStore()
        else:
            self.storage = storage
        self.default_ttl_seconds = default_ttl_seconds

    def create_approval(
        self,
        action_request: ActionRequest,
        policy_decision: PolicyDecision,
        ttl_seconds: Optional[int] = None,
    ) -> ApprovalRequest:
        appr_id = f"appr-{uuid.uuid4().hex[:8]}"
        ttl = ttl_seconds or self.default_ttl_seconds
        req_dt = datetime.now(timezone.utc)
        exp_dt = req_dt + timedelta(seconds=ttl)

        approval = ApprovalRequest(
            approval_id=appr_id,
            action_request=action_request,
            policy_decision=policy_decision,
            status="PENDING",
            requested_at=req_dt.isoformat(),
            expires_at=exp_dt.isoformat(),
        )
        self.storage.save_approval(approval)
        logger.info(f"Created ApprovalRequest '{appr_id}' for action '{action_request.action}' (TTL: {ttl}s)")
        return approval

    def get_approval(self, approval_id: str) -> Optional[ApprovalRequest]:
        approval = self.storage.get_approval(approval_id)
        if not approval:
            return None

        # Check for dynamic expiration
        if approval.status == "PENDING" and approval.is_expired():
            return self.expire(approval_id)
        return approval

    def list_pending(self) -> List[ApprovalRequest]:
        approvals = self.storage.list_approvals(status="PENDING")
        res = []
        for app in approvals:
            if app.is_expired():
                self.expire(app.approval_id)
            else:
                res.append(app)
        return res

    def list_all(self) -> List[ApprovalRequest]:
        return self.storage.list_approvals()

    def approve(
        self,
        approval_id: str,
        operator: OperatorIdentity,
        reason: Optional[str] = None,
    ) -> ApprovalRequest:
        app = self.get_approval(approval_id)
        if not app:
            raise ValueError(f"ApprovalRequest '{approval_id}' not found")

        if app.status != "PENDING":
            raise ValueError(f"Cannot approve request with status '{app.status}'. Only 'PENDING' requests may be approved.")

        if app.is_expired():
            self.expire(approval_id)
            raise ValueError(f"Cannot approve request '{approval_id}' because it has expired.")

        now_str = datetime.now(timezone.utc).isoformat()
        updated_dict = app.model_dump()
        updated_dict["status"] = "APPROVED"
        updated_dict["decided_at"] = now_str
        updated_dict["decided_by"] = operator.operator_id
        updated_dict["decision_reason"] = reason or "Approved by operator"

        updated = ApprovalRequest(**updated_dict)
        self.storage.update_approval(updated)

        record = ApprovalRecord(
            approval_id=approval_id,
            request_id=app.action_request.request_id,
            operator_id=operator.operator_id,
            decision="APPROVE",
            previous_status="PENDING",
            new_status="APPROVED",
            reason=reason,
            timestamp=now_str,
        )
        self.storage.record_audit(record)
        logger.info(f"Operator '{operator.operator_id}' APPROVED request '{approval_id}'")
        return updated

    def reject(
        self,
        approval_id: str,
        operator: OperatorIdentity,
        reason: Optional[str] = None,
    ) -> ApprovalRequest:
        app = self.get_approval(approval_id)
        if not app:
            raise ValueError(f"ApprovalRequest '{approval_id}' not found")

        if app.status != "PENDING":
            raise ValueError(f"Cannot reject request with status '{app.status}'. Only 'PENDING' requests may be rejected.")

        now_str = datetime.now(timezone.utc).isoformat()
        updated_dict = app.model_dump()
        updated_dict["status"] = "REJECTED"
        updated_dict["decided_at"] = now_str
        updated_dict["decided_by"] = operator.operator_id
        updated_dict["decision_reason"] = reason or "Rejected by operator"

        updated = ApprovalRequest(**updated_dict)
        self.storage.update_approval(updated)

        record = ApprovalRecord(
            approval_id=approval_id,
            request_id=app.action_request.request_id,
            operator_id=operator.operator_id,
            decision="REJECT",
            previous_status="PENDING",
            new_status="REJECTED",
            reason=reason,
            timestamp=now_str,
        )
        self.storage.record_audit(record)
        logger.info(f"Operator '{operator.operator_id}' REJECTED request '{approval_id}'")
        return updated

    def expire(self, approval_id: str) -> ApprovalRequest:
        app = self.storage.get_approval(approval_id)
        if not app:
            raise ValueError(f"ApprovalRequest '{approval_id}' not found")

        if app.status != "PENDING":
            return app

        now_str = datetime.now(timezone.utc).isoformat()
        updated_dict = app.model_dump()
        updated_dict["status"] = "EXPIRED"
        updated_dict["decided_at"] = now_str
        updated_dict["decision_reason"] = "Expired due to TTL timeout"

        updated = ApprovalRequest(**updated_dict)
        self.storage.update_approval(updated)

        record = ApprovalRecord(
            approval_id=approval_id,
            request_id=app.action_request.request_id,
            operator_id=None,
            decision="EXPIRE",
            previous_status="PENDING",
            new_status="EXPIRED",
            reason="Expired due to TTL timeout",
            timestamp=now_str,
        )
        self.storage.record_audit(record)
        return updated

    def consume(self, approval_id: str) -> ApprovalRequest:
        """
        Mark an APPROVED request as CONSUMED (single-use replay protection).
        """
        app = self.get_approval(approval_id)
        if not app:
            raise ValueError(f"ApprovalRequest '{approval_id}' not found")

        if app.status != "APPROVED":
            raise ValueError(f"Cannot consume approval with status '{app.status}'. Must be 'APPROVED'.")

        now_str = datetime.now(timezone.utc).isoformat()
        updated_dict = app.model_dump()
        updated_dict["status"] = "CONSUMED"
        updated_dict["consumed_at"] = now_str

        updated = ApprovalRequest(**updated_dict)
        self.storage.update_approval(updated)

        record = ApprovalRecord(
            approval_id=approval_id,
            request_id=app.action_request.request_id,
            operator_id=app.decided_by,
            decision="CONSUME",
            previous_status="APPROVED",
            new_status="CONSUMED",
            reason="Consumed for single-use execution",
            timestamp=now_str,
        )
        self.storage.record_audit(record)
        return updated
