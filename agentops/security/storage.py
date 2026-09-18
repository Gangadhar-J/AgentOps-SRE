import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional
from agentops.config import settings
from agentops.security.approval import ApprovalRecord, ApprovalRequest

logger = logging.getLogger("agentops.security.storage")


class SQLiteApprovalStore:
    """
    Durable, local SQLite storage engine for approval requests and audit records.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = settings.DB_PATH
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    action TEXT NOT NULL,
                    action_request_json TEXT NOT NULL,
                    policy_decision_json TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    decision_reason TEXT,
                    consumed_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS approval_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    approval_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    operator_id TEXT,
                    decision TEXT NOT NULL,
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    reason TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_approval(self, approval: ApprovalRequest) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO approvals (
                    approval_id, request_id, status, action,
                    action_request_json, policy_decision_json,
                    requested_at, expires_at, decided_at, decided_by,
                    decision_reason, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                approval.approval_id,
                approval.action_request.request_id,
                approval.status,
                approval.action_request.action,
                approval.action_request.model_dump_json(),
                approval.policy_decision.model_dump_json(),
                approval.requested_at,
                approval.expires_at,
                approval.decided_at,
                approval.decided_by,
                approval.decision_reason,
                approval.consumed_at,
            ))
            conn.commit()

    def update_approval(self, approval: ApprovalRequest) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE approvals SET
                    status = ?,
                    decided_at = ?,
                    decided_by = ?,
                    decision_reason = ?,
                    consumed_at = ?
                WHERE approval_id = ?
            """, (
                approval.status,
                approval.decided_at,
                approval.decided_by,
                approval.decision_reason,
                approval.consumed_at,
                approval.approval_id,
            ))
            conn.commit()

    def get_approval(self, approval_id: str) -> Optional[ApprovalRequest]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_approval(row)

    def list_approvals(self, status: Optional[str] = None) -> List[ApprovalRequest]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute("SELECT * FROM approvals WHERE status = ? ORDER BY requested_at DESC", (status,))
            else:
                cursor.execute("SELECT * FROM approvals ORDER BY requested_at DESC")
            rows = cursor.fetchall()
            return [self._row_to_approval(r) for r in rows]

    def record_audit(self, record: ApprovalRecord) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO approval_records (
                    approval_id, request_id, operator_id, decision,
                    previous_status, new_status, reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.approval_id,
                record.request_id,
                record.operator_id,
                record.decision,
                record.previous_status,
                record.new_status,
                record.reason,
                record.timestamp,
            ))
            conn.commit()

    def list_audit_records(self, approval_id: Optional[str] = None) -> List[ApprovalRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if approval_id:
                cursor.execute("SELECT * FROM approval_records WHERE approval_id = ? ORDER BY id ASC", (approval_id,))
            else:
                cursor.execute("SELECT * FROM approval_records ORDER BY id ASC")
            rows = cursor.fetchall()
            return [
                ApprovalRecord(
                    approval_id=r["approval_id"],
                    request_id=r["request_id"],
                    operator_id=r["operator_id"],
                    decision=r["decision"],
                    previous_status=r["previous_status"],
                    new_status=r["new_status"],
                    reason=r["reason"],
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    def _row_to_approval(self, row: sqlite3.Row) -> ApprovalRequest:
        action_req_dict = json.loads(row["action_request_json"])
        policy_dec_dict = json.loads(row["policy_decision_json"])
        return ApprovalRequest(
            approval_id=row["approval_id"],
            action_request=action_req_dict,
            policy_decision=policy_dec_dict,
            status=row["status"],
            requested_at=row["requested_at"],
            expires_at=row["expires_at"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            decision_reason=row["decision_reason"],
            consumed_at=row["consumed_at"],
        )
