from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from agentops.incident.models import IncidentReport


class InvestigationCancelledError(Exception):
    """Raised when an ongoing investigation is safely aborted due to operator cancellation."""
    pass


class LostJobLeaseError(Exception):
    """Raised when an active worker loses its lease ownership (e.g. lease expired and reclaimed)."""
    pass


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"
    CANCELLED = "CANCELLED"


class JobStage(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    COLLECTING_KUBERNETES = "collecting_kubernetes"
    QUERYING_PROMETHEUS = "querying_prometheus"
    QUERYING_LOKI = "querying_loki"
    EVIDENCE_COLLECTION_COMPLETED = "evidence_collection_completed"
    LLM_INFERENCE_STARTED = "llm_inference_started"
    LLM_INFERENCE_COMPLETED = "llm_inference_completed"
    VALIDATING_RCA = "validating_rca"
    EVALUATING_POLICY = "evaluating_policy"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


JobTriggerSource = Literal["UI", "CLI", "ALERT", "DEMO", "MANUAL"]


class InvestigationEvent(BaseModel):
    """An ordered lifecycle or stage progress event for an investigation job."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: int
    job_id: str
    event_type: str
    stage: str
    message: str
    payload: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class InvestigationJob(BaseModel):
    """Durable state representation of an asynchronous investigation."""
    model_config = ConfigDict(extra="forbid")

    job_id: str
    incident_id: str
    status: JobStatus = JobStatus.QUEUED
    stage: str = JobStage.QUEUED.value
    trigger_source: JobTriggerSource = "UI"
    namespace: str
    workload: str
    incident_description: Optional[str] = None
    provider: str
    model: Optional[str] = None
    dry_run: bool = False
    idempotency_key: Optional[str] = None
    worker_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    lease_expires_at: Optional[str] = None
    cancellation_requested: bool = False
    retry_count: int = 0
    notification_sent: bool = False
    trace_id: Optional[str] = None
    error_json: Optional[Dict[str, Any]] = None
    result: Optional[IncidentReport] = None


class WorkerStatus(BaseModel):
    """Snapshot of investigation worker pool and queue health."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    worker_id: str
    is_running: bool
    queue_depth: int
    active_jobs_count: int
    max_concurrent: int
    processed_count: int
    failed_count: int
    uptime_seconds: float
