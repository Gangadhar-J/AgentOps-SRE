from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class AlertItem(BaseModel):
    """A single alert instance inside an Alertmanager webhook payload."""
    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None
    fingerprint: Optional[str] = None


class AlertmanagerWebhookPayload(BaseModel):
    """
    Standard Prometheus Alertmanager webhook v4 payload.
    """
    model_config = ConfigDict(extra="ignore")

    version: str = "4"
    groupKey: Optional[str] = None
    truncatedAlerts: int = 0
    status: Literal["firing", "resolved"]
    receiver: Optional[str] = None
    groupLabels: Dict[str, str] = Field(default_factory=dict)
    commonLabels: Dict[str, str] = Field(default_factory=dict)
    commonAnnotations: Dict[str, str] = Field(default_factory=dict)
    externalURL: Optional[str] = None
    alerts: List[AlertItem] = Field(default_factory=list)


class AlertProcessingResult(BaseModel):
    """Result of processing an Alertmanager webhook submission."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str  # accepted, deduplicated, resolved, rejected, ignored
    alert_name: str
    namespace: Optional[str] = None
    workload: Optional[str] = None
    job_id: Optional[str] = None
    incident_id: Optional[str] = None
    message: str
    delivery_count: int = 1
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
