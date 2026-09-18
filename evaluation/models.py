from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExpectedRemediation(BaseModel):
    """
    Expected remediation proposal specification for a benchmark scenario.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(..., description="e.g. k8s.remediation.restart_deployment")
    resource_type: str = "deployment"
    resource_name: str = "demo-app"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = True


class ExpectedVerification(BaseModel):
    """
    Expected verification check specification.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    healthy: bool = True
    min_ready_replicas: Optional[int] = None
    expected_replicas: Optional[int] = None


class ScenarioDefinition(BaseModel):
    """
    Typed declarative scenario specification loaded from YAML.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    name: str
    description: str
    incident_type: str
    workload: str = "demo-app"
    namespace: str = "demo"
    severity: str = "HIGH"
    trigger_action: Optional[str] = None  # e.g. "crashloop", "bad-deployment"

    # Evaluation expectations
    expected_root_cause_keywords: List[str] = Field(default_factory=list)
    required_evidence_sources: List[str] = Field(default_factory=list)  # e.g. ["kubernetes", "loki"]
    forbidden_evidence_sources: List[str] = Field(default_factory=list)

    # Tool selection expectations
    required_tools: List[str] = Field(default_factory=list)
    allowed_tools: List[str] = Field(default_factory=list)
    forbidden_tools: List[str] = Field(default_factory=list)

    # Policy & remediation expectations
    expected_policy_behavior: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"] = "REQUIRE_APPROVAL"
    expected_remediation: Optional[ExpectedRemediation] = None
    expected_verification: Optional[ExpectedVerification] = None

    # Safety expectations
    is_adversarial: bool = False
    expected_mutation: bool = False  # Should this scenario legitimately mutate the cluster?
    max_allowed_tool_calls: int = 15
    max_duration_seconds: float = 300.0

    @field_validator("expected_root_cause_keywords", mode="before")
    @classmethod
    def coerce_keywords_to_str(cls, val):
        if isinstance(val, list):
            return [str(item) for item in val]
        return val


class EvaluationScores(BaseModel):
    """
    Structured per-dimension scoring (each 0.0 to 1.0).
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    rca_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    tool_selection: float = Field(default=0.0, ge=0.0, le=1.0)
    policy_compliance: float = Field(default=0.0, ge=0.0, le=1.0)
    remediation_correctness: float = Field(default=0.0, ge=0.0, le=1.0)
    verification_correctness: float = Field(default=0.0, ge=0.0, le=1.0)
    safety: float = Field(default=0.0, ge=0.0, le=1.0)
    efficiency: float = Field(default=0.0, ge=0.0, le=1.0)
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)


class EvaluationResult(BaseModel):
    """
    Immutable evaluation result for a single scenario execution.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str
    scenario_id: str
    scenario_name: str
    run_id: str
    mode: Literal["live", "replay"]
    provider: str
    model: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Scoring
    scores: EvaluationScores
    passed: bool

    # Critical Safety & Mutation tracking
    critical_safety_failure: bool = False
    infrastructure_mutated: bool = False
    unexpected_mutation: bool = False
    mutation_count: int = 0
    safety_violations: List[str] = Field(default_factory=list)

    # Details & Failures
    failures: List[str] = Field(default_factory=list)
    observations: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)

    # Metadata & Reproducibility
    agent_version: str = "0.6.0"
    evaluator_version: str = "0.6.0"
    configuration_hash: str = ""


class EvaluationRunSummary(BaseModel):
    """
    Aggregated evaluation summary for a multi-scenario run.
    """
    model_config = ConfigDict(frozen=False, extra="forbid")

    run_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mode: Literal["live", "replay"]
    provider: str
    model: str
    total_scenarios: int = 0
    passed_scenarios: int = 0
    failed_scenarios: int = 0
    overall_score: float = 0.0
    passed: bool = False

    # Safety rollups
    critical_safety_failures: int = 0
    total_mutations: int = 0
    unexpected_mutations: int = 0

    # Regression detection
    regression_detected: bool = False
    regression_details: List[str] = Field(default_factory=list)

    # Individual scenario results
    results: List[EvaluationResult] = Field(default_factory=list)


class BaselineRecord(BaseModel):
    """
    Stored evaluation baseline for regression comparisons.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    agent_version: str = "0.6.0"
    evaluator_version: str = "0.6.0"
    provider: str
    model: str
    overall_score: float
    average_duration_seconds: float
    scenario_scores: Dict[str, float] = Field(default_factory=dict)
    scenario_metrics: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


def compute_config_hash(content: str) -> str:
    """Compute SHA-256 hash of configuration content for provenance."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
