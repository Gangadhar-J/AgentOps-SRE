import os
import tempfile
from unittest.mock import patch
import pytest

from agentops.api.app import create_app
from agentops.incident.orchestrator import IncidentWorkflowManager
from agentops.security.approval import ApprovalManager
from agentops.security.gateway import SecurityGateway
from agentops.security.policy import PolicyEngine
from agentops.security.storage import SQLiteApprovalStore
from agentops.worker import (
    JobStage,
    JobStatus,
    JobStore,
)


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def job_store(temp_db):
    return JobStore(db_path=temp_db)


@pytest.fixture
def test_app(temp_db, job_store):
    store = SQLiteApprovalStore(db_path=temp_db)
    appr_mgr = ApprovalManager(storage=store)
    policy_engine = PolicyEngine(policy_file="config/policies.yaml")
    gateway = SecurityGateway(policy_engine=policy_engine, approval_manager=appr_mgr)
    workflow = IncidentWorkflowManager(gateway=gateway, approval_manager=appr_mgr)

    app = create_app(workflow_manager=workflow, job_store=job_store, start_worker=False)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(test_app):
    return test_app.test_client()


def test_job_durable_storage_before_acceptance(job_store):
    """Confirm investigation job is durably committed to SQLite before acceptance acknowledgment."""
    job, is_new = job_store.enqueue_job(
        job_id="job-durable-01",
        incident_id="inc-durable-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
        model="test-model",
    )
    assert is_new is True
    assert job.status == JobStatus.QUEUED
    assert job.stage == JobStage.QUEUED.value

    # Verify retrieval from a new JobStore connection instance (disk persistence)
    fresh_store = JobStore(db_path=job_store.db_path)
    fetched = fresh_store.get_job("job-durable-01")
    assert fetched is not None
    assert fetched.job_id == "job-durable-01"
    assert fetched.namespace == "demo"
    assert fetched.workload == "demo-app"


def test_idempotency_prevents_duplicate_active_jobs(job_store):
    """Submitting with the same idempotency key returns the existing job without creating duplicates."""
    job1, is_new1 = job_store.enqueue_job(
        job_id="job-idemp-01",
        incident_id="inc-idemp-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
        idempotency_key="idemp-key-12345",
    )
    assert is_new1 is True

    # Same key should return job1 and is_new=False
    job2, is_new2 = job_store.enqueue_job(
        job_id="job-idemp-02",
        incident_id="inc-idemp-02",
        namespace="demo",
        workload="demo-app",
        provider="mock",
        idempotency_key="idemp-key-12345",
    )
    assert is_new2 is False
    assert job2.job_id == job1.job_id
    assert job2.incident_id == job1.incident_id


def test_distinct_explicit_investigations_not_deduplicated(job_store):
    """Distinct submissions without matching idempotency keys are never suppressed."""
    job1, is_new1 = job_store.enqueue_job(
        job_id="job-dist-01",
        incident_id="inc-dist-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )
    job2, is_new2 = job_store.enqueue_job(
        job_id="job-dist-02",
        incident_id="inc-dist-02",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )
    assert is_new1 is True
    assert is_new2 is True
    assert job1.job_id != job2.job_id
    assert job_store.get_queue_stats()["queued"] == 2


def test_two_workers_cannot_claim_same_job(job_store):
    """Verify exclusive transactional lock prevents multiple workers claiming the same job."""
    job_store.enqueue_job(
        job_id="job-race-01",
        incident_id="inc-race-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    claimed1 = job_store.claim_next_job(worker_id="worker-A")
    assert claimed1 is not None
    assert claimed1.job_id == "job-race-01"
    assert claimed1.worker_id == "worker-A"

    # Worker B tries to claim simultaneously
    claimed2 = job_store.claim_next_job(worker_id="worker-B")
    assert claimed2 is None  # Queue is now empty of eligible jobs


def test_stale_lease_recovery(job_store):
    """A crashed worker that abandons a running job has its lease recovered after expiration."""
    job_store.enqueue_job(
        job_id="job-stale-01",
        incident_id="inc-stale-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    # Claim with short lease of 1 second
    claimed = job_store.claim_next_job(worker_id="crashed-worker", lease_seconds=1)
    assert claimed is not None
    assert claimed.status == JobStatus.RUNNING

    # Fast forward: manually set lease to past timestamp
    with job_store._get_connection() as conn:
        conn.execute(
            "UPDATE investigation_jobs SET lease_expires_at = '2020-01-01T00:00:00+00:00' WHERE job_id = ?",
            (claimed.job_id,),
        )
        conn.commit()

    # Recovery worker claims next job
    recovered = job_store.claim_next_job(worker_id="healthy-worker", lease_seconds=120)
    assert recovered is not None
    assert recovered.job_id == "job-stale-01"
    assert recovered.worker_id == "healthy-worker"
    assert recovered.retry_count == 1


def test_queued_job_safe_cancellation(job_store):
    """Cancelling a queued job transitions immediately to CANCELLED without worker execution."""
    job_store.enqueue_job(
        job_id="job-cancel-01",
        incident_id="inc-cancel-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    cancelled = job_store.request_cancellation("job-cancel-01")
    assert cancelled is True

    job = job_store.get_job("job-cancel-01")
    assert job.status == JobStatus.CANCELLED
    assert job.stage == JobStage.CANCELLED.value

    # Worker cannot claim cancelled job
    claimed = job_store.claim_next_job(worker_id="worker-1")
    assert claimed is None


def test_cancellation_during_execution(test_app, job_store):
    """Running worker halts cleanly if cancellation is requested before LLM inference."""
    job_store.enqueue_job(
        job_id="job-run-cancel",
        incident_id="inc-run-cancel",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    # Simulate cancellation request while job is claimed
    job = job_store.claim_next_job(worker_id="worker-test")
    assert job is not None
    job_store.request_cancellation(job.job_id)

    # Execute
    test_app.worker._execute_job(job)

    final_job = job_store.get_job(job.job_id)
    assert final_job.status == JobStatus.CANCELLED
    assert final_job.stage == JobStage.CANCELLED.value
    assert final_job.result is None  # Never falsely marked as successful!


def test_worker_status_and_queue_metrics(test_app, job_store):
    """Worker status endpoint reports accurate queue depth, concurrency, and worker metrics."""
    job_store.enqueue_job(
        job_id="job-metric-01",
        incident_id="inc-metric-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )
    job_store.enqueue_job(
        job_id="job-metric-02",
        incident_id="inc-metric-02",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    status = test_app.worker.get_status()
    assert status.queue_depth == 2
    assert status.max_concurrent == 1
    assert status.active_jobs_count == 0

    # Execute one
    assert test_app.worker.run_once() is True
    updated_status = test_app.worker.get_status()
    assert updated_status.queue_depth == 1
    assert updated_status.processed_count == 1


def test_queue_capacity_limit_enforced(test_app, client, job_store):
    """Submissions exceeding maximum queue capacity are rejected with 429."""
    with patch("agentops.config.settings.JOB_QUEUE_MAX_SIZE", 2):
        res1 = client.post("/api/incidents/investigate", json={"namespace": "demo", "workload": "demo-app", "provider": "mock"})
        assert res1.status_code == 202

        res2 = client.post("/api/incidents/investigate", json={"namespace": "demo", "workload": "demo-app", "provider": "mock"})
        assert res2.status_code == 202

        # 3rd request should exceed capacity
        res3 = client.post("/api/incidents/investigate", json={"namespace": "demo", "workload": "demo-app", "provider": "mock"})
        assert res3.status_code == 429
        data = res3.get_json()
        assert "capacity" in data["error"].lower()
        assert data["error_category"] == "QueueCapacityExceededError"


def test_job_lease_recovery_retry_exhaustion(job_store):
    """An abandoned job whose lease expires repeatedly is retried up to MAX_JOB_RETRIES, then safely fails."""
    job, _ = job_store.enqueue_job(
        job_id="job-exhaust-01",
        incident_id="inc-exhaust-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    # Claim and simulate expiration 3 times
    with patch("agentops.config.settings.MAX_JOB_RETRIES", 2):
        # 1st claim
        c1 = job_store.claim_next_job(worker_id="worker-dead-1")
        assert c1 is not None
        # Expire lease
        with job_store._get_connection() as conn:
            conn.execute("UPDATE investigation_jobs SET lease_expires_at = '2000-01-01T00:00:00' WHERE job_id = ?", (job.job_id,))
            conn.commit()

        # 2nd claim (recovers lease, retry_count becomes 1)
        c2 = job_store.claim_next_job(worker_id="worker-dead-2")
        assert c2 is not None
        assert c2.retry_count == 1
        # Expire lease again
        with job_store._get_connection() as conn:
            conn.execute("UPDATE investigation_jobs SET lease_expires_at = '2000-01-01T00:00:00' WHERE job_id = ?", (job.job_id,))
            conn.commit()

        # 3rd claim (recovers lease, retry_count becomes 2 == MAX_JOB_RETRIES)
        c3 = job_store.claim_next_job(worker_id="worker-dead-3")
        assert c3 is not None
        assert c3.retry_count == 2
        # Expire lease 3rd time
        with job_store._get_connection() as conn:
            conn.execute("UPDATE investigation_jobs SET lease_expires_at = '2000-01-01T00:00:00' WHERE job_id = ?", (job.job_id,))
            conn.commit()

        # 4th claim -> should detect retry_count >= MAX_JOB_RETRIES and mark job FAILED
        c4 = job_store.claim_next_job(worker_id="worker-dead-4")
        assert c4 is None  # No jobs left in queue

        exhausted_job = job_store.get_job(job.job_id)
        assert exhausted_job.status == JobStatus.FAILED
        assert exhausted_job.stage == JobStage.FAILED.value
        assert "exceeded maximum lease retries" in exhausted_job.error_json["error"].lower()


def test_zombie_worker_prevented_from_overwriting_job(job_store):
    """A worker that lost its lease cannot overwrite a job reclaimed and completed by another worker."""
    from agentops.incident.models import IncidentReport

    job, _ = job_store.enqueue_job(
        job_id="job-zombie-01",
        incident_id="inc-zombie-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    # Worker A claims job
    claimed_a = job_store.claim_next_job(worker_id="worker-A")
    assert claimed_a is not None

    # Lease expires on Worker A
    with job_store._get_connection() as conn:
        conn.execute("UPDATE investigation_jobs SET lease_expires_at = '2000-01-01T00:00:00' WHERE job_id = ?", (job.job_id,))
        conn.commit()

    # Worker B claims job
    claimed_b = job_store.claim_next_job(worker_id="worker-B")
    assert claimed_b is not None

    # Worker B finishes and completes job
    report_b = IncidentReport(
        incident_id=job.incident_id,
        namespace="demo",
        workload="demo-app",
        status="INVESTIGATED",
        source="MANUAL",
        incident_type="CrashLoopBackOff",
        root_cause="CrashLoopBackOff diagnosed by worker B",
        confidence=0.9,
        summary="Completed by Worker B",
    )
    ok_b = job_store.complete_job(job.job_id, report_b, worker_id="worker-B")
    assert ok_b is True

    # Zombie Worker A now attempts to complete with its stale result
    report_a = IncidentReport(
        incident_id=job.incident_id,
        namespace="demo",
        workload="demo-app",
        status="FAILED",
        source="MANUAL",
        incident_type="Unknown",
        root_cause="Stale diagnosis",
        confidence=0.1,
        summary="Stale report from zombie Worker A",
    )
    ok_a = job_store.complete_job(job.job_id, report_a, worker_id="worker-A")
    assert ok_a is False  # Rejected!

    # Also zombie Worker A cannot fail the job
    fail_a = job_store.fail_job(job.job_id, "Zombie error", worker_id="worker-A")
    assert fail_a is False  # Rejected!

    # Verify Worker B's result remains intact
    final_job = job_store.get_job(job.job_id)
    assert final_job.status == JobStatus.SUCCEEDED
    assert final_job.result.summary == "Completed by Worker B"


def test_smtp_failure_does_not_fail_investigation(test_app, job_store):
    """An SMTP notification failure never changes a successful investigation into a failure."""
    from unittest.mock import MagicMock
    from agentops.incident.models import IncidentReport

    job, _ = job_store.enqueue_job(
        job_id="job-smtp-fail-01",
        incident_id="inc-smtp-fail-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    claimed = job_store.claim_next_job(worker_id=test_app.worker.worker_id)
    assert claimed is not None

    # Mock workflow manager to return success
    mock_report = IncidentReport(
        incident_id=job.incident_id,
        namespace="demo",
        workload="demo-app",
        status="INVESTIGATED",
        source="MANUAL",
        incident_type="CrashLoopBackOff",
        root_cause="Diagnosed by test",
        confidence=0.95,
        summary="Successful diagnosis",
    )
    test_app.worker.workflow_manager.investigate_and_recommend = MagicMock(return_value=mock_report)

    # Patch send_investigation_outcome_email to raise SMTPException
    with patch(
        "agentops.notifications.email.send_investigation_outcome_email",
        side_effect=Exception("SMTP Connection refused by mailserver:587"),
    ):
        test_app.worker._execute_job(claimed)

    final_job = job_store.get_job(job.job_id)
    assert final_job.status == JobStatus.SUCCEEDED
    assert final_job.result.status == "INVESTIGATED"

    # Notification failure should be recorded in events timeline
    events = job_store.get_events(job.job_id)
    assert any(e.event_type == "notification_failed" for e in events)


def test_idempotent_notification_single_send(job_store):
    """Notification single-send guard ensures duplicate emails are never sent across retries."""
    job, _ = job_store.enqueue_job(
        job_id="job-notif-single-01",
        incident_id="inc-notif-single-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    # 1st attempt: claims send token
    first_send = job_store.mark_notification_sent(job.job_id)
    assert first_send is True

    # 2nd attempt (e.g. retry or concurrent completion): rejected
    second_send = job_store.mark_notification_sent(job.job_id)
    assert second_send is False


def test_heartbeat_renews_lease_during_extended_inference(test_app, job_store):
    """
    Heartbeat renewal keeps lease alive during extended LLM reasoning.
    Even when inference duration exceeds the initial lease duration, the background
    heartbeat continuously extends the lease so execution completes safely without split-brain.
    """
    import time
    from agentops.incident.models import IncidentReport
    from agentops.worker import JobStatus

    job, _ = job_store.enqueue_job(
        job_id="job-hb-renew-01",
        incident_id="inc-hb-renew-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    with patch("agentops.config.settings.JOB_LEASE_SECONDS", 0.3):
        claimed = job_store.claim_next_job(worker_id=test_app.worker.worker_id, lease_seconds=0.3)
        assert claimed is not None
        assert claimed.lease_expires_at is not None

        # Simulate slow LLM inference taking 0.5s (longer than the initial 0.3s lease)
        def slow_investigate(*args, **kwargs):
            time.sleep(0.5)
            return IncidentReport(
                incident_id="inc-hb-renew-01",
                namespace="demo",
                workload="demo-app",
                status="INVESTIGATED",
                source="MANUAL",
                incident_type="CrashLoopBackOff",
                root_cause="Extended LLM analysis completed successfully",
                confidence=0.92,
                summary="Heartbeat preserved lease during extended reasoning",
            )

        test_app.worker.workflow_manager.investigate_and_recommend = slow_investigate
        test_app.worker._execute_job(claimed)

    final_job = job_store.get_job(job.job_id)
    assert final_job.status == JobStatus.SUCCEEDED
    assert final_job.result.status == "INVESTIGATED"


def test_long_running_llm_inference_timeout_handling(test_app, job_store):
    """
    When an LLM inference call exceeds the configured timeout, InferenceTimeoutError
    is caught, categorized cleanly, marked FAILED, and zero unauthorized action is authorized.
    """
    from agentops.llm.exceptions import InferenceTimeoutError
    from agentops.worker import JobStatus

    job, _ = job_store.enqueue_job(
        job_id="job-timeout-01",
        incident_id="inc-timeout-01",
        namespace="demo",
        workload="demo-app",
        provider="ollama",
    )

    claimed = job_store.claim_next_job(worker_id=test_app.worker.worker_id, lease_seconds=60)
    assert claimed is not None

    def timeout_investigate(*args, **kwargs):
        raise InferenceTimeoutError(
            message="LLM reasoning exceeded configured timeout of 300.0s",
            provider="ollama",
            model="qwen3.5:2b",
        )

    test_app.worker.workflow_manager.investigate_and_recommend = timeout_investigate
    test_app.worker._execute_job(claimed)

    final_job = job_store.get_job(job.job_id)
    assert final_job.status == JobStatus.FAILED
    assert final_job.error_json is not None
    assert final_job.error_json["error_category"] == "InferenceTimeoutError"
    assert "timeout of 300.0s" in final_job.error_json["error"]

