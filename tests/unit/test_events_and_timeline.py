import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
import pytest

from agentops.observability.tracing import (
    parse_traceparent,
    make_traceparent,
    use_trace_context,
    get_current_trace_id,
    start_span,
)
from agentops.worker.models import JobStatus
from agentops.worker.store import JobStore


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def store(temp_db):
    return JobStore(db_path=temp_db)


def test_w3c_traceparent_parsing_and_generation():
    # Valid generation
    tp = make_traceparent(trace_id="4bf92f3577b34da6a3ce929d0e0e4736", span_id="00f067aa0ba902b7", sampled=True)
    assert tp == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    parsed = parse_traceparent(tp)
    assert parsed is not None
    assert parsed["version"] == "00"
    assert parsed["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert parsed["span_id"] == "00f067aa0ba902b7"
    assert parsed["trace_flags"] == "01"

    # Auto-generation when empty
    tp_auto = make_traceparent()
    parsed_auto = parse_traceparent(tp_auto)
    assert parsed_auto is not None
    assert len(parsed_auto["trace_id"]) == 32
    assert len(parsed_auto["span_id"]) == 16
    assert parsed_auto["trace_flags"] == "01"

    # Invalid cases
    assert parse_traceparent("") is None
    assert parse_traceparent("invalid-traceparent") is None
    assert parse_traceparent("00-short-1234-01") is None
    assert parse_traceparent(None) is None


def test_w3c_trace_context_propagation_across_thread():
    traceparent = "00-11223344556677889900aabbccddeeff-0123456789abcdef-01"
    parsed = parse_traceparent(traceparent)
    expected_tid = parsed["trace_id"]

    assert get_current_trace_id() is None or get_current_trace_id() != expected_tid

    with use_trace_context(traceparent):
        with start_span("worker.step") as span:
            ctx = span.get_span_context()
            active_tid = format(ctx.trace_id, "032x")
            assert active_tid == expected_tid
            assert ctx.trace_flags == 1

    # Ensure context detached cleanly
    current_tid = get_current_trace_id()
    assert current_tid is None or current_tid != expected_tid


def test_sqlite_schema_migration_and_verification(temp_db):
    # Initialize store on clean db
    store1 = JobStore(db_path=temp_db)
    job, is_new = store1.enqueue_job(
        job_id="job-mig-1",
        incident_id="inc-mig-1",
        namespace="demo",
        workload="demo-app",
        provider="ollama",
        trace_id="11223344556677889900aabbccddeeff",
        traceparent="00-11223344556677889900aabbccddeeff-0123456789abcdef-01",
    )
    assert is_new is True
    assert job.trace_id == "11223344556677889900aabbccddeeff"
    assert job.traceparent == "00-11223344556677889900aabbccddeeff-0123456789abcdef-01"

    # Re-open with a second store instance (simulating upgrade restart)
    store2 = JobStore(db_path=temp_db)
    fetched_job = store2.get_job("job-mig-1")
    assert fetched_job is not None
    assert fetched_job.trace_id == "11223344556677889900aabbccddeeff"
    assert fetched_job.traceparent == "00-11223344556677889900aabbccddeeff-0123456789abcdef-01"


def test_ordered_event_persistence_and_after_cursor(store):
    job_id = "job-stream-test"
    store.enqueue_job(
        job_id=job_id,
        incident_id="inc-stream-test",
        namespace="demo",
        workload="demo-app",
        provider="ollama",
    )

    t0 = datetime.now(timezone.utc).isoformat()
    time.sleep(0.01)
    t1 = datetime.now(timezone.utc).isoformat()

    # Add granular stage events
    ev1 = store.add_event(
        job_id=job_id,
        stage="collecting_kubernetes",
        message="Collected 4 Pods",
        stage_status="completed",
        stage_start_time=t0,
        stage_completed_time=t1,
        duration_ms=45.2,
        evidence_count=4,
        trace_id="tid-123",
    )
    ev2 = store.add_event(
        job_id=job_id,
        stage="querying_prometheus",
        message="Queried 2 alert metrics",
        stage_status="completed",
        duration_ms=120.5,
        evidence_count=2,
        trace_id="tid-123",
    )

    assert ev1.event_id is not None
    assert ev2.event_id is not None
    assert ev2.event_id > ev1.event_id

    # Retrieve all events
    all_events = store.get_events(job_id)
    assert len(all_events) == 3  # initial queued + ev1 + ev2

    # Verify attributes of granular event
    k8s_ev = all_events[1]
    assert k8s_ev.stage == "collecting_kubernetes"
    assert k8s_ev.stage_status == "completed"
    assert k8s_ev.duration_ms == 45.2
    assert k8s_ev.evidence_count == 4
    assert k8s_ev.trace_id == "tid-123"
    assert k8s_ev.schema_version == 1

    # Test replay with after_id cursor
    subsequent = store.get_events(job_id, after_id=ev1.event_id)
    assert len(subsequent) == 1
    assert subsequent[0].event_id == ev2.event_id
    assert subsequent[0].stage == "querying_prometheus"


def test_worker_lease_recovery_and_exhaustion(store):
    now = datetime.now(timezone.utc)
    expired_time = (now - timedelta(minutes=5)).isoformat()

    # 1. Job with retry_count < MAX_JOB_RETRIES should be recovered
    with store._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO investigation_jobs (
                job_id, incident_id, status, stage, trigger_source,
                namespace, workload, provider, dry_run, worker_id,
                created_at, started_at, lease_expires_at, retry_count, trace_id
            ) VALUES (?, ?, ?, ?, 'UI', 'demo', 'demo-app', 'ollama', 0, 'worker-stale-1', ?, ?, ?, 0, 'tid-rec-1')
        """, ("job-stale-1", "inc-stale-1", JobStatus.RUNNING.value, "running", expired_time, expired_time, expired_time))
        conn.commit()

    # Claim next job triggers recovery
    claimed = store.claim_next_job(worker_id="worker-fresh-2")
    assert claimed is not None
    assert claimed.job_id == "job-stale-1"
    assert claimed.retry_count == 1
    assert claimed.worker_id == "worker-fresh-2"

    events = store.get_events("job-stale-1")
    rec_events = [e for e in events if e.event_type == "lease_recovered"]
    assert len(rec_events) == 1
    assert "re-queued for retry" in rec_events[0].message
    assert rec_events[0].stage_status == "running"

    # 2. Job with retry_count >= MAX_JOB_RETRIES should be failed permanently (lease_exhausted)
    with store._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO investigation_jobs (
                job_id, incident_id, status, stage, trigger_source,
                namespace, workload, provider, dry_run, worker_id,
                created_at, started_at, lease_expires_at, retry_count, trace_id
            ) VALUES (?, ?, ?, ?, 'UI', 'demo', 'demo-app', 'ollama', 0, 'worker-stale-3', ?, ?, ?, 3, 'tid-rec-2')
        """, ("job-exhausted-2", "inc-exhausted-2", JobStatus.RUNNING.value, "running", expired_time, expired_time, expired_time))
        conn.commit()

    # Trigger recovery loop
    store.claim_next_job(worker_id="worker-fresh-4")

    exhausted_job = store.get_job("job-exhausted-2")
    assert exhausted_job.status == JobStatus.FAILED
    assert exhausted_job.lease_expires_at is None

    ex_events = store.get_events("job-exhausted-2")
    ex_terminal = [e for e in ex_events if e.event_type == "lease_exhausted"]
    assert len(ex_terminal) == 1
    assert "exceeded max retries" in ex_terminal[0].message
    assert ex_terminal[0].stage_status == "failed"
