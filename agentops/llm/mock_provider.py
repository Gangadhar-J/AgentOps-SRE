import time
from typing import Any, Dict, List, Tuple
from agentops.llm.base import BaseLLMProvider
from agentops.models.evidence import EvidenceType, InvestigationContext, TelemetrySource
from agentops.models.rca import (
    IncidentSeverity,
    IncidentType,
    RootCauseAnalysis,
    TimelineEvent,
)


class MockRuleBasedLLMProvider(BaseLLMProvider):
    """
    Deterministic rule-based reasoning engine for testing, offline evaluation,
    and air-gapped environments. Evaluates multi-modal evidence scores.
    """

    def __init__(self, model_name: str = "deterministic-rule-engine-v1"):
        self.model_name = model_name

    def generate_rca(self, context: InvestigationContext) -> Tuple[RootCauseAnalysis, Dict[str, Any]]:
        start_time = time.time()
        evidence_items = context.evidence_items

        oom_evidence_ids = []
        crash_evidence_ids = []
        err_500_evidence_ids = []
        bad_deployment_evidence_ids = []
        timeline = []

        score_oom = 0
        score_crash = 0
        score_500 = 0
        score_bad_deployment = 0

        for item in evidence_items:
            obs = item.observation.lower()

            # Resource Exhaustion / OOM signals
            if "oomkilled" in obs or "exit code 137" in obs:
                score_oom += 10
                oom_evidence_ids.append(item.id)
                timeline.append(TimelineEvent(
                    timestamp=item.timestamp.isoformat(),
                    source=item.source.value,
                    description=item.observation,
                    evidence_id=item.id,
                ))
            elif "memory allocation leak" in obs or "memory leak" in obs:
                score_oom += 5
                oom_evidence_ids.append(item.id)

            # CrashLoopBackOff signals (only if not an OOM termination)
            if ("crashloopbackoff" in obs or "exit code 1" in obs or "fatalprocesscrash" in obs) and "oomkilled" not in obs and "exit code 137" not in obs:
                score_crash += 10
                crash_evidence_ids.append(item.id)
                timeline.append(TimelineEvent(
                    timestamp=item.timestamp.isoformat(),
                    source=item.source.value,
                    description=item.observation,
                    evidence_id=item.id,
                ))
            elif ("fatal" in obs or "panic" in obs) and "oomkilled" not in obs:
                score_crash += 8
                crash_evidence_ids.append(item.id)
            elif ("back-off restarting" in obs or "backoff" in obs) and "oomkilled" not in obs and "exit code 137" not in obs:
                # Only attribute generic backoff to crash if OOM hasn't occurred
                score_crash += 4
                crash_evidence_ids.append(item.id)

            # High Error Rate signals
            if "5xx error rate" in obs or ("error rate is currently" in obs and "50" in obs):
                score_500 += 6
                err_500_evidence_ids.append(item.id)
                timeline.append(TimelineEvent(
                    timestamp=item.timestamp.isoformat(),
                    source=item.source.value,
                    description=item.observation,
                    evidence_id=item.id,
                ))
            elif "databaseconnectiontimeout" in obs or "connection timeout" in obs:
                score_500 += 5
                err_500_evidence_ids.append(item.id)

            # Bad Deployment / Rollback signals
            if "imagepullbackoff" in obs or "errimagepull" in obs or "broken-v2" in obs or "failed to pull image" in obs:
                score_bad_deployment += 6
                bad_deployment_evidence_ids.append(item.id)
                timeline.append(TimelineEvent(
                    timestamp=item.timestamp.isoformat(),
                    source=item.source.value,
                    description=item.observation,
                    evidence_id=item.id,
                ))
            elif "bad deployment" in obs or "rollback" in obs or "invalid image" in obs:
                score_bad_deployment += 4
                bad_deployment_evidence_ids.append(item.id)

        telemetry_coverage = {
            source: status.available
            for source, status in context.telemetry_status.items()
        }

        # Determine dominant incident hypothesis
        max_score = max(score_oom, score_crash, score_500, score_bad_deployment)

        if max_score == 0:
            incident_type = IncidentType.UNKNOWN
            severity = IncidentSeverity.LOW
            summary = f"No active failure mode or critical anomaly detected for workload '{context.workload}'."
            root_cause = "All inspected telemetry indicates normal healthy operation or insufficient error telemetry."
            confidence = 0.40
            evidence_ids = [e.id for e in evidence_items[:2]] if evidence_items else []
            recommended_action = "Continue monitoring telemetry. No immediate remediation required."

        elif max_score == score_bad_deployment:
            incident_type = IncidentType.BAD_DEPLOYMENT
            severity = IncidentSeverity.HIGH
            summary = f"Workload '{context.workload}' failed deployment rollout due to invalid image or broken release revision."
            root_cause = (
                "A recent deployment update specified an unresolvable image reference or broken container configuration, "
                "causing new replica pods to enter ImagePullBackOff/ErrImagePull and failing rollout progression."
            )
            confidence = 0.95 if (score_bad_deployment >= 6) else 0.82
            evidence_ids = bad_deployment_evidence_ids
            recommended_action = (
                "1. Roll back deployment to the previous stable revision.\n"
                "2. Verify container image repository tags in CI/CD pipeline.\n"
                "3. Monitor post-rollback rollout health."
            )

        elif max_score == score_oom:
            incident_type = IncidentType.RESOURCE_EXHAUSTION
            severity = IncidentSeverity.CRITICAL
            summary = f"Workload '{context.workload}' experienced container termination due to memory exhaustion (OOMKilled)."
            root_cause = (
                "A background worker process engaged in continuous unconstrained heap allocation "
                "without releasing buffers, causing the container memory to exceed its 128Mi cgroups limit. "
                "The Linux kernel invoked the OOM killer, terminating the container process (exit code 137)."
            )
            confidence = 0.95 if (score_oom >= 6) else 0.80
            evidence_ids = oom_evidence_ids
            recommended_action = (
                "1. Increase container memory limits to provide temporary operational headroom.\n"
                "2. Patch background buffer accumulation in order processing worker.\n"
                "3. Roll out fixed image tag."
            )

        elif max_score == score_crash:
            incident_type = IncidentType.CRASHLOOP_BACKOFF
            severity = IncidentSeverity.CRITICAL
            summary = f"Workload '{context.workload}' entered CrashLoopBackOff following unhandled process panics."
            root_cause = (
                "The application encountered a fatal segmentation fault/panic triggered upon reaching the request threshold. "
                "The container terminated with exit code 1 and failed liveness checks repeatedly, causing Kubernetes to engage restart backoff."
            )
            confidence = 0.95 if (score_crash >= 6) else 0.80
            evidence_ids = crash_evidence_ids
            recommended_action = (
                "1. Inspect stack trace in crash logs to isolate the panic condition.\n"
                "2. Roll back deployment to the previous stable replica set.\n"
                "3. Deploy hotfix for unhandled exception handling."
            )

        else:
            incident_type = IncidentType.HIGH_ERROR_RATE
            severity = IncidentSeverity.HIGH
            summary = f"Workload '{context.workload}' experienced elevated HTTP 500 error rates on the '/orders' endpoint."
            root_cause = (
                "Intermittent database connection pool exhaustion caused connection timeouts (DatabaseConnectionTimeout) "
                "when committing order transactions to the database replica, resulting in HTTP 500 responses."
            )
            confidence = 0.92 if (score_500 >= 6) else 0.78
            evidence_ids = err_500_evidence_ids
            recommended_action = (
                "1. Verify database pool capacity and upstream database health.\n"
                "2. Adjust connection pool size and timeout thresholds.\n"
                "3. Verify readiness probe configuration."
            )

        rca = RootCauseAnalysis(
            investigation_id=context.investigation_id,
            incident_type=incident_type,
            severity=severity,
            summary=summary,
            root_cause=root_cause,
            confidence=confidence,
            evidence_ids=evidence_ids,
            timeline=timeline,
            recommended_action=recommended_action,
            requires_human_approval=True,
            telemetry_coverage=telemetry_coverage,
        )

        metadata = {
            "provider": "mock",
            "model": self.model_name,
            "latency_seconds": round(time.time() - start_time, 4),
            "prompt_tokens": len(str(context.model_dump())) // 4,
            "completion_tokens": len(rca.model_dump_json()) // 4,
        }
        return rca, metadata
