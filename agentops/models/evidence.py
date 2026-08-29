from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidenceType(str, Enum):
    FACT = "FACT"              # Directly measured telemetry, log line, or API status
    INFERENCE = "INFERENCE"    # Synthesized conclusion derived from multiple facts
    HYPOTHESIS = "HYPOTHESIS"  # Proposed explanation requiring further confirmation


class TelemetrySource(str, Enum):
    KUBERNETES = "kubernetes"
    PROMETHEUS = "prometheus"
    LOKI = "loki"
    SYSTEM = "system"


class EvidenceItem(BaseModel):
    id: str = Field(description="Unique stable evidence identifier, e.g. E001")
    source: TelemetrySource
    evidence_type: EvidenceType = EvidenceType.FACT
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resource: str = Field(description="Target resource identifier, e.g. demo/demo-app-xxx or demo-app")
    metric_or_query: str = Field(description="Metric name, LogQL query, or Kubernetes API path queried")
    observation: str = Field(description="Human-readable factual observation")
    severity: Optional[str] = Field(default="INFO", description="INFO, WARN, ERROR, CRITICAL")
    raw_payload: Optional[Dict[str, Any]] = Field(default=None, description="Optional raw telemetry extract")


class TelemetryStatus(BaseModel):
    source: TelemetrySource
    available: bool
    query_count: int = 0
    error_message: Optional[str] = None


class InvestigationContext(BaseModel):
    investigation_id: str
    namespace: str
    workload: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    telemetry_status: Dict[str, TelemetryStatus] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_evidence(
        self,
        source: TelemetrySource,
        resource: str,
        metric_or_query: str,
        observation: str,
        evidence_type: EvidenceType = EvidenceType.FACT,
        severity: str = "INFO",
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> EvidenceItem:
        evidence_id = f"E{len(self.evidence_items) + 1:03d}"
        item = EvidenceItem(
            id=evidence_id,
            source=source,
            evidence_type=evidence_type,
            resource=resource,
            metric_or_query=metric_or_query,
            observation=observation,
            severity=severity,
            raw_payload=raw_payload,
        )
        self.evidence_items.append(item)
        return item
