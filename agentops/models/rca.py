from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IncidentType(str, Enum):
    CRASHLOOP_BACKOFF = "CrashLoopBackOff"
    HIGH_ERROR_RATE = "HighErrorRate"
    RESOURCE_EXHAUSTION = "ResourceExhaustion"
    UNKNOWN = "Unknown"


class IncidentSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TimelineEvent(BaseModel):
    timestamp: str
    source: str
    description: str
    evidence_id: Optional[str] = None


class AgentObservabilityMetrics(BaseModel):
    investigation_id: str
    duration_seconds: float = Field(description="Total investigation execution time in seconds")
    k8s_query_count: int = 0
    prometheus_query_count: int = 0
    loki_query_count: int = 0
    llm_latency_seconds: float = 0.0
    llm_provider: str = "unknown"
    llm_model: str = "unknown"
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    errors: List[str] = Field(default_factory=list)
    telemetry_availability: Dict[str, bool] = Field(default_factory=dict)


class RootCauseAnalysis(BaseModel):
    investigation_id: str
    incident_type: IncidentType
    severity: IncidentSeverity
    summary: str = Field(description="Concise summary of what occurred")
    root_cause: str = Field(description="Evidence-backed diagnosis of the underlying cause")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0 based on telemetry coverage and agreement")
    evidence_ids: List[str] = Field(description="List of Evidence IDs (e.g. ['E001', 'E002']) supporting the diagnosis")
    timeline: List[TimelineEvent] = Field(default_factory=list, description="Chronological timeline of observed telemetry events")
    recommended_action: str = Field(description="Human-actionable remediation recommendation")
    requires_human_approval: bool = Field(default=True, description="Strictly True for all remediation proposals")
    telemetry_coverage: Dict[str, bool] = Field(default_factory=dict, description="Indicates availability of Kubernetes, Prometheus, Loki during investigation")
    agent_metrics: Optional[AgentObservabilityMetrics] = None
