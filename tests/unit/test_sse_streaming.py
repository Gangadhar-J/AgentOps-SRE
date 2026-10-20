import os
import tempfile
import pytest

from agentops.api.app import create_app
from agentops.incident.orchestrator import IncidentWorkflowManager
from agentops.security.approval import ApprovalManager
from agentops.security.gateway import SecurityGateway
from agentops.security.policy import PolicyEngine
from agentops.security.storage import SQLiteApprovalStore
from agentops.worker import JobStore


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


def test_ordered_events_retrieval(job_store, client):
    """Verify investigation events are persisted in monotonic order."""
    job, _ = job_store.enqueue_job(
        job_id="job-sse-01",
        incident_id="inc-sse-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    job_store.add_event(job.job_id, "collecting_kubernetes", "Checking pod health...")
    job_store.add_event(job.job_id, "querying_prometheus", "Querying metrics...")
    job_store.add_event(job.job_id, "llm_inference_started", "Running LLM inference...")

    res = client.get(f"/api/investigations/{job.job_id}/events")
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 4  # 1 initial queued + 3 added
    stages = [e["stage"] for e in data["events"]]
    assert stages == ["queued", "collecting_kubernetes", "querying_prometheus", "llm_inference_started"]
    assert data["events"][0]["event_id"] < data["events"][1]["event_id"] < data["events"][2]["event_id"]


def test_events_pagination_with_after_parameter(job_store, client):
    """Querying ?after=<id> returns only subsequent events."""
    job, _ = job_store.enqueue_job(
        job_id="job-sse-02",
        incident_id="inc-sse-02",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )
    e1 = job_store.add_event(job.job_id, "stage_1", "Message 1")
    job_store.add_event(job.job_id, "stage_2", "Message 2")
    job_store.add_event(job.job_id, "stage_3", "Message 3")

    # Fetch after e1
    res = client.get(f"/api/investigations/{job.job_id}/events?after={e1.event_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 2
    assert [e["stage"] for e in data["events"]] == ["stage_2", "stage_3"]


def test_result_endpoint_returns_409_while_pending(job_store, client):
    """Result endpoint returns 409 Conflict until the job reaches a terminal state."""
    job, _ = job_store.enqueue_job(
        job_id="job-pending-01",
        incident_id="inc-pending-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )

    res = client.get(f"/api/investigations/{job.job_id}/result")
    assert res.status_code == 409
    data = res.get_json()
    assert data["status"] == "pending"
    assert data["job_status"] == "QUEUED"


def test_sse_stream_format_and_termination(test_app, job_store, client):
    """Verify Server-Sent Events stream format id, event, and final terminal event."""
    job, _ = job_store.enqueue_job(
        job_id="job-stream-01",
        incident_id="inc-stream-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
        dry_run=True,
    )

    # Worker executes job to terminal state
    assert test_app.worker.run_once() is True

    # Connect to SSE stream
    stream_res = client.get(f"/api/investigations/{job.job_id}/stream")
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.content_type

    content = stream_res.data.decode("utf-8")
    assert "event: investigation_queued" in content
    assert "event: investigation_started" in content
    assert "event: done" in content
    assert "data: " in content


def test_sse_reconnection_with_last_event_id(job_store, client):
    """Supplying Last-Event-ID header skips already delivered events."""
    job, _ = job_store.enqueue_job(
        job_id="job-reconn-01",
        incident_id="inc-reconn-01",
        namespace="demo",
        workload="demo-app",
        provider="mock",
    )
    e1 = job_store.add_event(job.job_id, "first_stage", "First message")
    job_store.add_event(job.job_id, "second_stage", "Second message")

    # Mark completed so stream terminates
    from agentops.incident.models import IncidentReport
    report = IncidentReport(
        incident_id=job.incident_id,
        namespace=job.namespace,
        workload=job.workload,
        status="INVESTIGATED",
        source="MANUAL",
        incident_type="CrashLoopBackOff",
        confidence=0.95,
        summary="Test incident",
        root_cause="Pod crashed",
    )
    job_store.complete_job(job.job_id, report)

    # Request with Last-Event-ID = e1.event_id
    stream_res = client.get(
        f"/api/investigations/{job.job_id}/stream",
        headers={"Last-Event-ID": str(e1.event_id)},
    )
    assert stream_res.status_code == 200
    content = stream_res.data.decode("utf-8")
    assert "first_stage" not in content  # Skipped!
    assert "second_stage" in content     # Delivered!
    assert "event: done" in content
