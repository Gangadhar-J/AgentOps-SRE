from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# -------------------------------------------------------------
# Kubernetes Tool Schemas
# -------------------------------------------------------------
class K8sGetPodHealthInput(BaseModel):
    namespace: str = Field(default="demo", description="Kubernetes namespace")
    app: Optional[str] = Field(default="demo-app", description="Workload / application label name")
    pod: Optional[str] = Field(default=None, description="Specific pod name to inspect")


class K8sGetDeploymentHealthInput(BaseModel):
    namespace: str = Field(default="demo", description="Kubernetes namespace")
    deployment: str = Field(default="demo-app", description="Deployment resource name")


class K8sGetEventsInput(BaseModel):
    namespace: str = Field(default="demo", description="Kubernetes namespace")
    resource_name: Optional[str] = Field(default=None, description="Filter events for a specific resource name")
    limit: int = Field(default=30, ge=1, le=100, description="Maximum number of warning events to return")


# -------------------------------------------------------------
# Prometheus Tool Schemas
# -------------------------------------------------------------
class PromQueryErrorRateInput(BaseModel):
    app: str = Field(default="demo-app", description="Workload / application label")
    namespace: str = Field(default="demo", description="Kubernetes namespace")
    duration: str = Field(default="2m", pattern=r"^[0-9]+[smhd]$", description="PromQL rate window (e.g. 1m, 2m, 5m)")


class PromQueryLatencyInput(BaseModel):
    app: str = Field(default="demo-app", description="Workload / application label")
    namespace: str = Field(default="demo", description="Kubernetes namespace")
    quantile: float = Field(default=0.95, ge=0.0, le=1.0, description="Latency quantile (e.g. 0.50, 0.95, 0.99)")
    duration: str = Field(default="5m", pattern=r"^[0-9]+[smhd]$", description="PromQL rate window")


class PromQueryMemoryInput(BaseModel):
    app: str = Field(default="demo-app", description="Workload / application label")
    namespace: str = Field(default="demo", description="Kubernetes namespace")


# -------------------------------------------------------------
# Loki Tool Schemas
# -------------------------------------------------------------
class LokiSearchErrorsInput(BaseModel):
    namespace: str = Field(default="demo", description="Kubernetes namespace")
    app: str = Field(default="demo-app", description="Application label")
    lookback_seconds: int = Field(default=90, ge=10, le=3600, description="Lookback window in seconds")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum log entries to return")


class LokiSearchByRequestIdInput(BaseModel):
    request_id: str = Field(..., description="Unique request ID / trace ID to correlate")
    namespace: str = Field(default="demo", description="Kubernetes namespace")
    lookback_minutes: int = Field(default=10, ge=1, le=120, description="Lookback window in minutes")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum log entries to return")
