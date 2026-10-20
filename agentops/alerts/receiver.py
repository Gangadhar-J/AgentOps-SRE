from datetime import datetime, timezone, timedelta
import hmac
import logging
import re
from typing import Any, Dict, List, Optional
import uuid

from agentops.alerts.models import (
    AlertmanagerWebhookPayload,
    AlertProcessingResult,
)
from agentops.config import settings
from agentops.worker.models import JobStatus
from agentops.worker.store import JobStore

logger = logging.getLogger("agentops.alerts")

_K8S_NAME_REGEX = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def _is_valid_k8s_name(name: str) -> bool:
    return bool(name and len(name) <= 63 and _K8S_NAME_REGEX.match(name))


class AlertmanagerReceiver:
    """
    Ingests, validates, deduplicates, and routes Prometheus Alertmanager alerts
    to durable asynchronous investigation jobs without running synchronous inference.
    """

    def __init__(self, job_store: Optional[JobStore] = None):
        self.job_store = job_store or JobStore()

    def validate_auth(self, headers: Dict[str, str], query_token: Optional[str] = None) -> bool:
        """
        Validate shared-secret token if ALERTMANAGER_SECRET is configured.
        Uses constant-time comparison (hmac.compare_digest).
        Prioritizes HTTP header authentication (Authorization: Bearer or X-Alertmanager-Secret).
        Query string authentication (?secret=) is deprecated and blocked unless explicitly allowed.
        """
        expected = settings.ALERTMANAGER_SECRET.strip()
        if not expected:
            return True  # Open boundary for local development when not configured

        # 1. Prefer standard Authorization: Bearer <token>
        auth_header = headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if hmac.compare_digest(token, expected):
                return True

        # 2. Prefer dedicated X-Alertmanager-Secret header
        header_token = headers.get("X-Alertmanager-Secret", "").strip()
        if header_token and hmac.compare_digest(header_token, expected):
            return True

        # 3. Query string token (discouraged due to URL logging in proxies/servers)
        if query_token and query_token.strip():
            if not settings.ALERTMANAGER_ALLOW_QUERY_AUTH:
                logger.warning(
                    "Alertmanager authentication via query parameter (?secret=...) was rejected. "
                    "URLs leak into access logs. Configure HTTP Authorization headers instead or enable ALERTMANAGER_ALLOW_QUERY_AUTH=true."
                )
                return False

            logger.warning(
                "DEPRECATION WARNING: Alertmanager authenticated via query parameter (?secret=...). "
                "URLs may leak in access logs and proxies. Configure HTTP Authorization headers instead."
            )
            if hmac.compare_digest(query_token.strip(), expected):
                return True

        return False

    def process_webhook(
        self,
        payload_data: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> List[AlertProcessingResult]:
        """
        Validate and process Alertmanager webhook payload.
        Returns a list of processing results (one per distinct alert target).
        """
        try:
            payload = AlertmanagerWebhookPayload.model_validate(payload_data)
        except Exception as e:
            logger.warning(f"Malformed Alertmanager webhook payload: {e}")
            return [
                AlertProcessingResult(
                    status="rejected",
                    alert_name="unknown",
                    message=f"Malformed Alertmanager payload schema: {str(e)}",
                )
            ]

        results: List[AlertProcessingResult] = []

        # If payload has individual alerts, process each; otherwise use common labels
        alerts_to_process = payload.alerts if payload.alerts else []
        if not alerts_to_process:
            # Fallback to group/common labels
            dummy_alert = {
                "status": payload.status,
                "labels": {**payload.groupLabels, **payload.commonLabels},
                "annotations": payload.commonAnnotations,
            }
            alerts_to_process = [dummy_alert]

        for item in alerts_to_process:
            labels = getattr(item, "labels", {}) if hasattr(item, "labels") else item.get("labels", {})
            annotations = getattr(item, "annotations", {}) if hasattr(item, "annotations") else item.get("annotations", {})
            item_status = getattr(item, "status", payload.status) if hasattr(item, "status") else item.get("status", payload.status)

            alert_name = labels.get("alertname", labels.get("alert_name", "UnknownAlert"))
            raw_ns = labels.get("namespace", labels.get("kubernetes_namespace", settings.DEFAULT_NAMESPACE))
            raw_wl = labels.get("workload", labels.get("app", labels.get("deployment", "demo-app")))

            # 1. Target Validation
            if not _is_valid_k8s_name(raw_ns) or not _is_valid_k8s_name(raw_wl):
                logger.warning(f"Alert '{alert_name}' rejected: invalid target '{raw_ns}/{raw_wl}'")
                results.append(
                    AlertProcessingResult(
                        status="rejected",
                        alert_name=alert_name,
                        namespace=raw_ns,
                        workload=raw_wl,
                        message=f"Target namespace '{raw_ns}' or workload '{raw_wl}' fails Kubernetes naming validation.",
                    )
                )
                continue

            namespace = raw_ns.lower()
            workload = raw_wl.lower()
            fingerprint = getattr(item, "fingerprint", None)
            if not fingerprint and isinstance(item, dict):
                fingerprint = item.get("fingerprint")

            # 2. Handle Resolved State
            if item_status == "resolved":
                self._record_resolution(alert_name, namespace, workload, fingerprint=fingerprint)
                results.append(
                    AlertProcessingResult(
                        status="resolved",
                        alert_name=alert_name,
                        namespace=namespace,
                        workload=workload,
                        message=f"Alert '{alert_name}' resolution acknowledged for {namespace}/{workload}.",
                    )
                )
                continue

            # 3. Deduplication & Active Job Check
            dedup_result = self._check_deduplication_and_enqueue(
                alert_name=alert_name,
                namespace=namespace,
                workload=workload,
                annotations=annotations,
                fingerprint=fingerprint,
                trace_id=trace_id,
            )
            results.append(dedup_result)

        return results

    def _check_deduplication_and_enqueue(
        self,
        alert_name: str,
        namespace: str,
        workload: str,
        annotations: Dict[str, str],
        fingerprint: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> AlertProcessingResult:
        """Atomically evaluate deduplication window and enqueue investigation if eligible."""
        now_dt = datetime.now(timezone.utc)
        now_str = now_dt.isoformat()
        dedup_key = f"{alert_name}:{namespace}:{workload}:{fingerprint}" if fingerprint else f"{alert_name}:{namespace}:{workload}"
        cooldown_seconds = settings.ALERT_COOLDOWN_SECONDS

        with self.job_store._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            # Check existing deduplication record
            cursor.execute("SELECT * FROM alert_deduplication WHERE dedup_key = ?", (dedup_key,))
            existing = cursor.fetchone()

            # Check if there is an active (QUEUED or RUNNING) job for this workload
            cursor.execute("""
                SELECT job_id FROM investigation_jobs
                WHERE namespace = ? AND workload = ? AND status IN (?, ?)
                ORDER BY created_at DESC LIMIT 1
            """, (namespace, workload, JobStatus.QUEUED.value, JobStatus.RUNNING.value))
            active_job_row = cursor.fetchone()

            if active_job_row:
                active_job_id = active_job_row["job_id"]
                count = (existing["count"] + 1) if existing else 1
                if existing:
                    cursor.execute("""
                        UPDATE alert_deduplication
                        SET last_seen_at = ?, last_status = 'firing', count = count + 1
                        WHERE dedup_key = ?
                    """, (now_str, dedup_key))
                else:
                    cursor.execute("""
                        INSERT INTO alert_deduplication (
                            dedup_key, alert_name, namespace, workload,
                            first_seen_at, last_seen_at, last_status, job_id, count
                        ) VALUES (?, ?, ?, ?, ?, ?, 'firing', ?, 1)
                    """, (dedup_key, alert_name, namespace, workload, now_str, now_str, active_job_id))
                conn.commit()

                logger.info(
                    f"Deduplicated alert '{alert_name}' for {namespace}/{workload}: active job '{active_job_id}' in progress (count: {count})"
                )
                return AlertProcessingResult(
                    status="deduplicated",
                    alert_name=alert_name,
                    namespace=namespace,
                    workload=workload,
                    job_id=active_job_id,
                    message=f"Active investigation '{active_job_id}' is already processing this workload.",
                    delivery_count=count,
                )

            # Check cooldown window ONLY if the alert was NOT previously resolved
            if existing and existing["last_status"] != "resolved" and existing["cooldown_until"]:
                cooldown_until_str = existing["cooldown_until"]
                try:
                    cooldown_dt = datetime.fromisoformat(cooldown_until_str)
                    if now_dt < cooldown_dt:
                        cursor.execute("""
                            UPDATE alert_deduplication
                            SET last_seen_at = ?, count = count + 1
                            WHERE dedup_key = ?
                        """, (now_str, dedup_key))
                        conn.commit()

                        logger.info(
                            f"Suppressed alert '{alert_name}' for {namespace}/{workload} within cooldown window until {cooldown_until_str}"
                        )
                        return AlertProcessingResult(
                            status="deduplicated",
                            alert_name=alert_name,
                            namespace=namespace,
                            workload=workload,
                            job_id=existing["job_id"],
                            message=f"Alert suppressed under cooldown policy (cooldown until {cooldown_until_str}).",
                            delivery_count=existing["count"] + 1,
                        )
                except Exception:
                    pass

            # Eligible for fresh investigation! Check queue depth first
            cursor.execute("SELECT COUNT(*) as cnt FROM investigation_jobs WHERE status = ?", (JobStatus.QUEUED.value,))
            q_cnt = cursor.fetchone()["cnt"]
            if q_cnt >= settings.JOB_QUEUE_MAX_SIZE:
                conn.commit()
                logger.warning(f"Alert '{alert_name}' rejected: investigation queue full ({q_cnt} jobs)")
                return AlertProcessingResult(
                    status="rejected",
                    alert_name=alert_name,
                    namespace=namespace,
                    workload=workload,
                    message=f"Investigation queue at maximum capacity ({settings.JOB_QUEUE_MAX_SIZE}). Alert dropped safely.",
                )

            # Enqueue fresh investigation
            job_id = f"job-{uuid.uuid4().hex[:8]}"
            incident_id = f"inc-{uuid.uuid4().hex[:8]}"
            desc_text = annotations.get("summary") or annotations.get("description") or f"Prometheus alert '{alert_name}' firing"
            cooldown_exp = (now_dt + timedelta(seconds=cooldown_seconds)).isoformat()

            cursor.execute("""
                INSERT INTO investigation_jobs (
                    job_id, incident_id, status, stage, trigger_source,
                    namespace, workload, incident_description, provider,
                    model, dry_run, created_at, trace_id
                ) VALUES (?, ?, ?, ?, 'ALERT', ?, ?, ?, ?, ?, 0, ?, ?)
            """, (
                job_id,
                incident_id,
                JobStatus.QUEUED.value,
                "queued",
                namespace,
                workload,
                f"[{alert_name}] {desc_text}",
                settings.LLM_PROVIDER,
                settings.LLM_MODEL,
                now_str,
                trace_id,
            ))

            cursor.execute("""
                INSERT INTO investigation_events (
                    job_id, event_type, stage, message, payload_json, timestamp
                ) VALUES (?, ?, 'queued', ?, ?, ?)
            """, (
                job_id,
                "investigation_queued",
                f"Investigation queued from Alertmanager webhook (Alert: {alert_name})",
                '{"source": "ALERT"}',
                now_str,
            ))

            # Record or update alert_deduplication
            if existing:
                cursor.execute("""
                    UPDATE alert_deduplication
                    SET last_seen_at = ?, last_status = 'firing', job_id = ?, count = count + 1, cooldown_until = ?
                    WHERE dedup_key = ?
                """, (now_str, job_id, cooldown_exp, dedup_key))
            else:
                cursor.execute("""
                    INSERT INTO alert_deduplication (
                        dedup_key, alert_name, namespace, workload,
                        first_seen_at, last_seen_at, last_status, job_id, count, cooldown_until
                    ) VALUES (?, ?, ?, ?, ?, ?, 'firing', ?, 1, ?)
                """, (dedup_key, alert_name, namespace, workload, now_str, now_str, job_id, cooldown_exp))

            conn.commit()

        logger.info(f"Accepted Alertmanager alert '{alert_name}' -> queued investigation job '{job_id}'")
        return AlertProcessingResult(
            status="accepted",
            alert_name=alert_name,
            namespace=namespace,
            workload=workload,
            job_id=job_id,
            incident_id=incident_id,
            message=f"Alert accepted and investigation job '{job_id}' queued.",
            delivery_count=1,
        )

    def _record_resolution(
        self,
        alert_name: str,
        namespace: str,
        workload: str,
        fingerprint: Optional[str] = None,
    ) -> None:
        """Record resolved status in deduplication store and clear active cooldown."""
        now = datetime.now(timezone.utc).isoformat()
        dedup_key = f"{alert_name}:{namespace}:{workload}:{fingerprint}" if fingerprint else f"{alert_name}:{namespace}:{workload}"
        with self.job_store._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE alert_deduplication
                SET last_seen_at = ?, last_status = 'resolved', cooldown_until = NULL
                WHERE dedup_key = ?
            """, (now, dedup_key))
            conn.commit()

    def list_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recently seen alert deduplication records for UI operator console."""
        with self.job_store._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM alert_deduplication
                ORDER BY last_seen_at DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
