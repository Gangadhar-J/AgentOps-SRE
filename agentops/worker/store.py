from datetime import datetime, timezone, timedelta
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from agentops.config import settings
from agentops.incident.models import IncidentReport
from agentops.worker.models import (
    InvestigationEvent,
    InvestigationJob,
    JobStage,
    JobStatus,
    JobTriggerSource,
)

logger = logging.getLogger("agentops.worker.store")


class JobStore:
    """
    Durable, thread-safe SQLite-backed storage for investigation jobs,
    lifecycle state transitions, and ordered progress events.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = settings.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # WAL mode enables concurrent readers while writing
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS investigation_jobs (
                    job_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    trigger_source TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    workload TEXT NOT NULL,
                    incident_description TEXT,
                    provider TEXT NOT NULL,
                    model TEXT,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    idempotency_key TEXT UNIQUE,
                    worker_id TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    lease_expires_at TEXT,
                    cancellation_requested INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    notification_sent INTEGER NOT NULL DEFAULT 0,
                    trace_id TEXT,
                    error_json TEXT,
                    result_json TEXT
                )
            """)

            # Ensure notification_sent column exists in existing database files
            try:
                cursor.execute("ALTER TABLE investigation_jobs ADD COLUMN notification_sent INTEGER NOT NULL DEFAULT 0;")
            except sqlite3.OperationalError:
                pass

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS investigation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT,
                    timestamp TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_deduplication (
                    dedup_key TEXT PRIMARY KEY,
                    alert_name TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    workload TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_status TEXT NOT NULL,
                    job_id TEXT,
                    count INTEGER NOT NULL DEFAULT 1,
                    cooldown_until TEXT
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON investigation_jobs (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON investigation_jobs (created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_job_id ON investigation_events (job_id, id);")
            conn.commit()

    def enqueue_job(
        self,
        job_id: str,
        incident_id: str,
        namespace: str,
        workload: str,
        provider: str,
        model: Optional[str] = None,
        incident_description: Optional[str] = None,
        dry_run: bool = False,
        trigger_source: JobTriggerSource = "UI",
        idempotency_key: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Tuple[InvestigationJob, bool]:
        """
        Durably enqueue an investigation job before acknowledging acceptance.
        Returns: (job, is_new). If idempotency_key matches an existing job,
        returns the existing job with is_new=False.
        """
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Check idempotency first if key provided
            if idempotency_key:
                cursor.execute(
                    "SELECT * FROM investigation_jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                existing = cursor.fetchone()
                if existing:
                    return self._row_to_job(existing), False

            try:
                cursor.execute("""
                    INSERT INTO investigation_jobs (
                        job_id, incident_id, status, stage, trigger_source,
                        namespace, workload, incident_description, provider,
                        model, dry_run, idempotency_key, created_at, trace_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_id,
                    incident_id,
                    JobStatus.QUEUED.value,
                    JobStage.QUEUED.value,
                    trigger_source,
                    namespace,
                    workload,
                    incident_description,
                    provider,
                    model,
                    1 if dry_run else 0,
                    idempotency_key,
                    now,
                    trace_id,
                ))

                # Insert initial queued event
                cursor.execute("""
                    INSERT INTO investigation_events (
                        job_id, event_type, stage, message, payload_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    job_id,
                    "investigation_queued",
                    JobStage.QUEUED.value,
                    f"Investigation queued for workload '{namespace}/{workload}' using {provider}:{model or 'default'}",
                    json.dumps({"trigger_source": trigger_source}),
                    now,
                ))

                conn.commit()
            except sqlite3.IntegrityError:
                if idempotency_key:
                    cursor.execute(
                        "SELECT * FROM investigation_jobs WHERE idempotency_key = ?",
                        (idempotency_key,),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        return self._row_to_job(existing), False
                raise

        job = self.get_job(job_id)
        if not job:
            raise RuntimeError(f"Failed to retrieve newly enqueued job '{job_id}'")
        return job, True

    def claim_next_job(
        self,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> Optional[InvestigationJob]:
        """
        Transactionally claim the next available queued job using an exclusive lock.
        Also recovers stale abandoned jobs whose lease has expired.
        """
        now_dt = datetime.now(timezone.utc)
        now_str = now_dt.isoformat()
        lease_exp = (now_dt + timedelta(seconds=lease_seconds)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            # 1a. Fail jobs that exceeded MAX_JOB_RETRIES due to expired worker leases
            max_retries = settings.MAX_JOB_RETRIES
            cursor.execute("""
                SELECT job_id, worker_id, retry_count FROM investigation_jobs
                WHERE status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at < ? AND retry_count >= ? AND cancellation_requested = 0
            """, (JobStatus.RUNNING.value, now_str, max_retries))
            exhausted_rows = cursor.fetchall()
            for r in exhausted_rows:
                jid = r["job_id"]
                prev_w = r["worker_id"]
                cursor.execute("""
                    UPDATE investigation_jobs
                    SET status = ?, stage = ?, completed_at = ?, lease_expires_at = NULL, error_json = ?
                    WHERE job_id = ? AND status = ?
                """, (
                    JobStatus.FAILED.value,
                    JobStage.FAILED.value,
                    now_str,
                    json.dumps({
                        "error": f"Job exceeded maximum lease retries ({max_retries}). Worker '{prev_w}' was unresponsive.",
                        "error_category": "LeaseTimeoutError",
                        "timestamp": now_str,
                    }),
                    jid,
                    JobStatus.RUNNING.value,
                ))
                cursor.execute("""
                    INSERT INTO investigation_events (
                        job_id, event_type, stage, message, payload_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    jid,
                    "lease_exhausted",
                    JobStage.FAILED.value,
                    f"Job failed: exceeded maximum retries ({max_retries}) due to worker lease timeouts",
                    json.dumps({"worker_id": prev_w, "max_retries": max_retries}),
                    now_str,
                ))

            # 1b. Recover expired leases whose retry_count < MAX_JOB_RETRIES
            cursor.execute("""
                SELECT job_id, worker_id, retry_count FROM investigation_jobs
                WHERE status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at < ? AND retry_count < ? AND cancellation_requested = 0
            """, (JobStatus.RUNNING.value, now_str, max_retries))
            recoverable_rows = cursor.fetchall()
            for r in recoverable_rows:
                jid = r["job_id"]
                prev_w = r["worker_id"]
                new_retry = r["retry_count"] + 1
                cursor.execute("""
                    UPDATE investigation_jobs
                    SET status = ?, worker_id = NULL, lease_expires_at = NULL, retry_count = ?
                    WHERE job_id = ? AND status = ?
                """, (JobStatus.QUEUED.value, new_retry, jid, JobStatus.RUNNING.value))
                cursor.execute("""
                    INSERT INTO investigation_events (
                        job_id, event_type, stage, message, payload_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    jid,
                    "lease_recovered",
                    JobStage.QUEUED.value,
                    f"Job lease expired (worker '{prev_w}' unresponsive); re-queued for retry (attempt {new_retry}/{max_retries})",
                    json.dumps({"prev_worker_id": prev_w, "retry_count": new_retry}),
                    now_str,
                ))

            # 2. Find oldest eligible job
            cursor.execute("""
                SELECT job_id FROM investigation_jobs
                WHERE status = ? AND cancellation_requested = 0
                ORDER BY created_at ASC
                LIMIT 1
            """, (JobStatus.QUEUED.value,))

            row = cursor.fetchone()
            if not row:
                conn.commit()
                return None

            job_id = row["job_id"]

            # 3. Atomically claim it
            cursor.execute("""
                UPDATE investigation_jobs
                SET status = ?, stage = ?, worker_id = ?, started_at = ?, lease_expires_at = ?
                WHERE job_id = ? AND status = ?
            """, (
                JobStatus.RUNNING.value,
                JobStage.STARTING.value,
                worker_id,
                now_str,
                lease_exp,
                job_id,
                JobStatus.QUEUED.value,
            ))

            if cursor.rowcount == 0:
                conn.commit()
                return None

            # 4. Log started event
            cursor.execute("""
                INSERT INTO investigation_events (
                    job_id, event_type, stage, message, payload_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                "investigation_started",
                JobStage.STARTING.value,
                f"Investigation claimed and started by worker '{worker_id}'",
                json.dumps({"worker_id": worker_id}),
                now_str,
            ))

            conn.commit()

        return self.get_job(job_id)

    def renew_lease(self, job_id: str, worker_id: str, lease_seconds: int = 120) -> bool:
        """Renew active job lease to prevent abandonment recovery during long LLM inference."""
        lease_exp = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE investigation_jobs
                SET lease_expires_at = ?
                WHERE job_id = ? AND worker_id = ? AND status = ?
            """, (lease_exp, job_id, worker_id, JobStatus.RUNNING.value))
            conn.commit()
            return cursor.rowcount > 0

    def add_event(
        self,
        job_id: str,
        stage: str,
        message: str,
        event_type: str = "progress",
        payload: Optional[Dict[str, Any]] = None,
    ) -> InvestigationEvent:
        """Record an ordered progress event and update current job stage."""
        now = datetime.now(timezone.utc).isoformat()
        payload_str = json.dumps(payload) if payload is not None else None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO investigation_events (
                    job_id, event_type, stage, message, payload_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (job_id, event_type, stage, message, payload_str, now))
            event_id = cursor.lastrowid

            # Keep job's current stage in sync
            cursor.execute("""
                UPDATE investigation_jobs
                SET stage = ?
                WHERE job_id = ? AND status = ?
            """, (stage, job_id, JobStatus.RUNNING.value))

            conn.commit()

        return InvestigationEvent(
            event_id=event_id,
            job_id=job_id,
            event_type=event_type,
            stage=stage,
            message=message,
            payload=payload,
            timestamp=now,
        )

    def complete_job(
        self,
        job_id: str,
        report: IncidentReport,
        worker_id: Optional[str] = None,
    ) -> bool:
        """
        Mark job as successfully completed with final IncidentReport.
        If worker_id is provided, ensures only the current lease owner can complete the job.
        Returns True if updated successfully, False if worker lost ownership or job not RUNNING.
        """
        now = datetime.now(timezone.utc).isoformat()
        is_success = report.status not in ("FAILED", "INCOMPLETE")
        status = JobStatus.SUCCEEDED.value if is_success else JobStatus.FAILED.value
        stage = JobStage.COMPLETED.value if is_success else JobStage.FAILED.value

        with self._get_connection() as conn:
            cursor = conn.cursor()
            if worker_id:
                cursor.execute("""
                    UPDATE investigation_jobs
                    SET status = ?, stage = ?, completed_at = ?, result_json = ?, lease_expires_at = NULL
                    WHERE job_id = ? AND status IN (?, ?) AND (worker_id = ? OR worker_id IS NULL)
                """, (status, stage, now, report.model_dump_json(), job_id, JobStatus.RUNNING.value, JobStatus.QUEUED.value, worker_id))
            else:
                cursor.execute("""
                    UPDATE investigation_jobs
                    SET status = ?, stage = ?, completed_at = ?, result_json = ?, lease_expires_at = NULL
                    WHERE job_id = ? AND status IN (?, ?)
                """, (status, stage, now, report.model_dump_json(), job_id, JobStatus.RUNNING.value, JobStatus.QUEUED.value))

            if cursor.rowcount == 0:
                logger.warning(
                    f"complete_job: Job '{job_id}' could not be completed by worker '{worker_id}' (not in active status or lease transferred)."
                )
                conn.commit()
                return False

            cursor.execute("""
                INSERT INTO investigation_events (
                    job_id, event_type, stage, message, payload_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                "investigation_completed" if is_success else "investigation_failed",
                stage,
                f"Investigation finished with status: {report.status} (Diagnosis: {report.incident_type})",
                json.dumps({
                    "incident_id": report.incident_id,
                    "confidence": report.confidence,
                    "validation_passed": report.validation_passed,
                    "duration_seconds": report.duration_seconds,
                    "worker_id": worker_id,
                }),
                now,
            ))
            conn.commit()
            return True

    def fail_job(
        self,
        job_id: str,
        error_message: str,
        error_category: Optional[str] = None,
        is_incomplete: bool = False,
        worker_id: Optional[str] = None,
    ) -> bool:
        """
        Mark job as terminal failure or incomplete.
        If worker_id is provided, ensures only the current lease owner can fail the job.
        Returns True if updated successfully, False if worker lost ownership or job not RUNNING.
        """
        now = datetime.now(timezone.utc).isoformat()
        status = JobStatus.INCOMPLETE.value if is_incomplete else JobStatus.FAILED.value
        stage = JobStage.FAILED.value
        err_dict = {
            "error": error_message,
            "error_category": error_category or "ExecutionError",
            "worker_id": worker_id,
            "timestamp": now,
        }

        with self._get_connection() as conn:
            cursor = conn.cursor()
            if worker_id:
                cursor.execute("""
                    UPDATE investigation_jobs
                    SET status = ?, stage = ?, completed_at = ?, error_json = ?, lease_expires_at = NULL
                    WHERE job_id = ? AND status IN (?, ?) AND (worker_id = ? OR worker_id IS NULL)
                """, (status, stage, now, json.dumps(err_dict), job_id, JobStatus.RUNNING.value, JobStatus.QUEUED.value, worker_id))
            else:
                cursor.execute("""
                    UPDATE investigation_jobs
                    SET status = ?, stage = ?, completed_at = ?, error_json = ?, lease_expires_at = NULL
                    WHERE job_id = ? AND status IN (?, ?)
                """, (status, stage, now, json.dumps(err_dict), job_id, JobStatus.RUNNING.value, JobStatus.QUEUED.value))

            if cursor.rowcount == 0:
                logger.warning(
                    f"fail_job: Job '{job_id}' could not be failed by worker '{worker_id}' (not in active status or lease transferred)."
                )
                conn.commit()
                return False

            cursor.execute("""
                INSERT INTO investigation_events (
                    job_id, event_type, stage, message, payload_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                "investigation_failed" if not is_incomplete else "investigation_incomplete",
                stage,
                f"Investigation failed: {error_message}",
                json.dumps(err_dict),
                now,
            ))
            conn.commit()
            return True

    def mark_notification_sent(self, job_id: str) -> bool:
        """
        Atomically mark notification as sent for this job.
        Returns True if successfully transitioned from 0 to 1 (first sender wins).
        Returns False if notification was already sent.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE investigation_jobs
                SET notification_sent = 1
                WHERE job_id = ? AND notification_sent = 0
            """, (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def request_cancellation(self, job_id: str) -> bool:
        """
        Request cancellation of a job.
        If still QUEUED, immediately transitions to CANCELLED.
        If RUNNING, sets cancellation_requested=1 for worker to check.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # If queued, cancel immediately
            cursor.execute("""
                UPDATE investigation_jobs
                SET status = ?, stage = ?, completed_at = ?, cancellation_requested = 1
                WHERE job_id = ? AND status = ?
            """, (JobStatus.CANCELLED.value, JobStage.CANCELLED.value, now, job_id, JobStatus.QUEUED.value))

            if cursor.rowcount > 0:
                cursor.execute("""
                    INSERT INTO investigation_events (
                        job_id, event_type, stage, message, payload_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    job_id,
                    "investigation_cancelled",
                    JobStage.CANCELLED.value,
                    "Investigation cancelled before execution by operator request",
                    None,
                    now,
                ))
                conn.commit()
                return True

            # If running, flag cancellation request
            cursor.execute("""
                UPDATE investigation_jobs
                SET cancellation_requested = 1
                WHERE job_id = ? AND status = ?
            """, (job_id, JobStatus.RUNNING.value))

            conn.commit()
            return cursor.rowcount > 0

    def mark_cancelled(self, job_id: str) -> None:
        """Mark a running job as gracefully terminated due to cancellation request."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE investigation_jobs
                SET status = ?, stage = ?, completed_at = ?, lease_expires_at = NULL
                WHERE job_id = ?
            """, (JobStatus.CANCELLED.value, JobStage.CANCELLED.value, now, job_id))

            cursor.execute("""
                INSERT INTO investigation_events (
                    job_id, event_type, stage, message, payload_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                "investigation_cancelled",
                JobStage.CANCELLED.value,
                "Investigation aborted by operator cancellation",
                None,
                now,
            ))
            conn.commit()

    def get_job(self, job_id: str) -> Optional[InvestigationJob]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM investigation_jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def get_events(self, job_id: str, after_id: Optional[int] = None) -> List[InvestigationEvent]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if after_id is not None:
                cursor.execute(
                    "SELECT * FROM investigation_events WHERE job_id = ? AND id > ? ORDER BY id ASC",
                    (job_id, after_id),
                )
            else:
                cursor.execute(
                    "SELECT * FROM investigation_events WHERE job_id = ? ORDER BY id ASC",
                    (job_id,),
                )
            rows = cursor.fetchall()
            return [self._row_to_event(r) for r in rows]

    def list_jobs(self, limit: int = 50, status: Optional[str] = None) -> List[InvestigationJob]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM investigation_jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM investigation_jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [self._row_to_job(r) for r in rows]

    def get_queue_stats(self) -> Dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM investigation_jobs WHERE status = ?", (JobStatus.QUEUED.value,))
            queued = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM investigation_jobs WHERE status = ?", (JobStatus.RUNNING.value,))
            running = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM investigation_jobs WHERE status = ?", (JobStatus.SUCCEEDED.value,))
            succeeded = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM investigation_jobs WHERE status = ?", (JobStatus.FAILED.value,))
            failed = cursor.fetchone()["cnt"]

            return {
                "queued": queued,
                "running": running,
                "succeeded": succeeded,
                "failed": failed,
                "total_active": queued + running,
            }

    def _row_to_job(self, row: sqlite3.Row) -> InvestigationJob:
        res_json = row["result_json"]
        result = IncidentReport.model_validate_json(res_json) if res_json else None

        err_json = row["error_json"]
        error_data = json.loads(err_json) if err_json else None

        return InvestigationJob(
            job_id=row["job_id"],
            incident_id=row["incident_id"],
            status=JobStatus(row["status"]),
            stage=row["stage"],
            trigger_source=row["trigger_source"],
            namespace=row["namespace"],
            workload=row["workload"],
            incident_description=row["incident_description"],
            provider=row["provider"],
            model=row["model"],
            dry_run=bool(row["dry_run"]),
            idempotency_key=row["idempotency_key"],
            worker_id=row["worker_id"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            lease_expires_at=row["lease_expires_at"],
            cancellation_requested=bool(row["cancellation_requested"]),
            retry_count=row["retry_count"],
            notification_sent=bool(row["notification_sent"]) if "notification_sent" in row.keys() else False,
            trace_id=row["trace_id"],
            error_json=error_data,
            result=result,
        )

    def _row_to_event(self, row: sqlite3.Row) -> InvestigationEvent:
        p_json = row["payload_json"]
        payload = json.loads(p_json) if p_json else None
        return InvestigationEvent(
            event_id=row["id"],
            job_id=row["job_id"],
            event_type=row["event_type"],
            stage=row["stage"],
            message=row["message"],
            payload=payload,
            timestamp=row["timestamp"],
        )
