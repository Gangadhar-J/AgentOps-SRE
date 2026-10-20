import logging
import os
import threading
import time
from typing import Any, Dict, Optional
import uuid

from agentops.config import settings
from agentops.incident.models import IncidentReport
from agentops.incident.orchestrator import IncidentWorkflowManager
from agentops.worker.models import (
    InvestigationCancelledError,
    InvestigationJob,
    LostJobLeaseError,
    WorkerStatus,
)
from agentops.worker.store import JobStore

logger = logging.getLogger("agentops.worker")


class InvestigationWorker:
    """
    Lightweight, durable background worker that claims queued investigations,
    monitors job leases, reports ordered progress events, and executes the
    full incident investigation workflow.
    """

    def __init__(
        self,
        job_store: Optional[JobStore] = None,
        workflow_manager: Optional[IncidentWorkflowManager] = None,
        worker_id: Optional[str] = None,
        max_concurrent: Optional[int] = None,
        poll_interval: float = 0.5,
    ):
        self.job_store = job_store or JobStore()
        self.workflow_manager = workflow_manager or IncidentWorkflowManager()
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.max_concurrent = max_concurrent or settings.MAX_CONCURRENT_INVESTIGATIONS
        self.poll_interval = poll_interval

        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._active_jobs: Dict[str, InvestigationJob] = {}
        self._lock = threading.Lock()

        # Metrics
        self.start_time = time.time()
        self.processed_count = 0
        self.failed_count = 0

    def start(self) -> None:
        """Start worker thread(s) in background."""
        if self._threads:
            logger.warning(f"Worker {self.worker_id} is already running.")
            return

        self._stop_event.clear()
        for i in range(self.max_concurrent):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"{self.worker_id}-thread-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

        logger.info(
            f"InvestigationWorker '{self.worker_id}' started with {self.max_concurrent} worker thread(s)"
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal worker to stop and wait for active threads."""
        logger.info(f"Stopping InvestigationWorker '{self.worker_id}'...")
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads.clear()
        logger.info(f"InvestigationWorker '{self.worker_id}' stopped.")

    def run_once(self) -> bool:
        """
        Poll and execute a single job if available. Returns True if a job was processed.
        Useful for synchronous test executions and step-by-step validation.
        """
        with self._lock:
            if len(self._active_jobs) >= self.max_concurrent:
                return False

        job = self.job_store.claim_next_job(
            worker_id=self.worker_id,
            lease_seconds=settings.JOB_LEASE_SECONDS,
        )
        if not job:
            return False

        with self._lock:
            self._active_jobs[job.job_id] = job

        try:
            self._execute_job(job)
            self.processed_count += 1
        except Exception as e:
            self.failed_count += 1
            logger.exception(f"Unhandled error processing job '{job.job_id}': {e}")
            self.job_store.fail_job(
                job_id=job.job_id,
                error_message=str(e),
                error_category=type(e).__name__,
            )
        finally:
            with self._lock:
                self._active_jobs.pop(job.job_id, None)

        return True

    def _worker_loop(self) -> None:
        """Continuous polling loop for a worker thread."""
        while not self._stop_event.is_set():
            try:
                processed = self.run_once()
                if not processed:
                    time.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                time.sleep(self.poll_interval)

    def _execute_job(self, job: InvestigationJob) -> None:
        """Execute the end-to-end incident investigation for a claimed job."""
        logger.info(
            f"Executing investigation job '{job.job_id}' (incident: {job.incident_id}, workload: {job.namespace}/{job.workload}, provider: {job.provider})"
        )

        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()

        def heartbeat_loop():
            # Renew at 1/3 of the lease duration (e.g. 40s for 120s lease; min 0.1s for tests, max 40.0s for long leases)
            interval = max(0.1, min(40.0, settings.JOB_LEASE_SECONDS / 3.0))
            while not heartbeat_stop.wait(interval):
                renewed = self.job_store.renew_lease(
                    job_id=job.job_id,
                    worker_id=self.worker_id,
                    lease_seconds=settings.JOB_LEASE_SECONDS,
                )
                if not renewed:
                    logger.warning(
                        f"Worker '{self.worker_id}' lost lease on job '{job.job_id}' (ownership expired or stolen)."
                    )
                    lease_lost.set()
                    break

        hb_thread = threading.Thread(
            target=heartbeat_loop,
            name=f"heartbeat-{job.job_id}",
            daemon=True,
        )
        hb_thread.start()

        def on_progress(stage: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
            if lease_lost.is_set():
                raise LostJobLeaseError(f"Lease on job '{job.job_id}' was lost or expired.")
            self.job_store.add_event(
                job_id=job.job_id,
                stage=stage,
                message=message,
                payload=payload,
            )
            # Instant renewal on stage transition
            self.job_store.renew_lease(
                job_id=job.job_id,
                worker_id=self.worker_id,
                lease_seconds=settings.JOB_LEASE_SECONDS,
            )

        def check_cancellation() -> bool:
            if lease_lost.is_set():
                raise LostJobLeaseError(f"Lease on job '{job.job_id}' was lost or expired.")
            current = self.job_store.get_job(job.job_id)
            return bool(current and current.cancellation_requested)

        # Check cancellation before starting heavy operations
        if check_cancellation():
            logger.info(f"Job '{job.job_id}' was cancelled before execution began.")
            heartbeat_stop.set()
            self.job_store.mark_cancelled(job.job_id)
            return

        try:
            report = self.workflow_manager.investigate_and_recommend(
                namespace=job.namespace,
                workload=job.workload,
                incident_description=job.incident_description,
                provider_name=job.provider,
                model_name=job.model,
                dry_run=job.dry_run,
                source=job.trigger_source,
                incident_id=job.incident_id,
                progress_callback=on_progress,
                cancellation_check=check_cancellation,
            )

            if check_cancellation():
                self.job_store.mark_cancelled(job.job_id)
                return

            completed = self.job_store.complete_job(job.job_id, report, worker_id=self.worker_id)
            if completed:
                logger.info(f"Job '{job.job_id}' completed with report status '{report.status}'.")
                # Deliver outcome notification safely (never fails the job, never sends duplicates)
                self._dispatch_outcome_notification(job, report)
            else:
                logger.warning(
                    f"Job '{job.job_id}' was not completed by worker '{self.worker_id}': ownership lost or job not running."
                )

        except InvestigationCancelledError:
            logger.info(f"Job '{job.job_id}' execution cancelled during investigation.")
            self.job_store.mark_cancelled(job.job_id)
        except LostJobLeaseError as e:
            logger.warning(f"Aborting execution of job '{job.job_id}' by worker '{self.worker_id}': {e}")
        except Exception as e:
            err_cat = getattr(e, "error_category", type(e).__name__)
            err_msg = str(e)
            logger.error(f"Investigation job '{job.job_id}' failed ({err_cat}): {err_msg}")
            self.job_store.fail_job(
                job_id=job.job_id,
                error_message=err_msg,
                error_category=err_cat,
                worker_id=self.worker_id,
            )
        finally:
            heartbeat_stop.set()
            hb_thread.join(timeout=1.0)

    def _dispatch_outcome_notification(self, job: InvestigationJob, report: IncidentReport) -> None:
        """Deliver outcome email notification if not already sent. Errors never fail the job."""
        if not self.job_store.mark_notification_sent(job.job_id):
            logger.debug(f"Notification already sent for job '{job.job_id}', skipping duplicate.")
            return

        try:
            from agentops.notifications.email import send_investigation_outcome_email
            res = send_investigation_outcome_email(
                report=report,
                alert_name=job.incident_description,
            )
            if res.get("sent"):
                self.job_store.add_event(
                    job_id=job.job_id,
                    stage=job.stage,
                    message=f"Investigation outcome notification email sent to {settings.NOTIFICATION_EMAIL_TO}",
                    event_type="notification_sent",
                    payload=res,
                )
        except Exception as e:
            logger.error(f"Failed to send outcome notification for job '{job.job_id}': {e}")
            self.job_store.add_event(
                job_id=job.job_id,
                stage=job.stage,
                message=f"Outcome email notification failed to send: {str(e)}",
                event_type="notification_failed",
                payload={"error": str(e), "error_category": type(e).__name__},
            )

    def get_status(self) -> WorkerStatus:
        stats = self.job_store.get_queue_stats()
        with self._lock:
            active_count = len(self._active_jobs)

        is_running = any(t.is_alive() for t in self._threads) if self._threads else False
        uptime = round(time.time() - self.start_time, 1)

        return WorkerStatus(
            worker_id=self.worker_id,
            is_running=is_running,
            queue_depth=stats["queued"],
            active_jobs_count=active_count,
            max_concurrent=self.max_concurrent,
            processed_count=self.processed_count,
            failed_count=self.failed_count,
            uptime_seconds=uptime,
        )
