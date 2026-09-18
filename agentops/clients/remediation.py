from datetime import datetime, timezone
import json
import logging
import subprocess
import time
from typing import Any, Dict, List, Optional
from agentops.config import settings
from agentops.models.remediation import PreRemediationSnapshot, RemediationVerification

logger = logging.getLogger("agentops.remediation")


class KubernetesRemediationClient:
    """
    Controlled, narrowly scoped Kubernetes Client for remediation execution.
    
    Security Boundary Guarantee:
    This client exclusively exposes three specific remediation operations:
    1. restart_deployment()
    2. scale_deployment()
    3. rollback_deployment()
    
    It rejects and never exposes generic delete, exec, apply, or raw patch methods.
    """

    def __init__(self, timeout: Optional[int] = None):
        self.timeout = timeout or settings.TELEMETRY_TIMEOUT_SECONDS

    def _execute_controlled_cmd(self, args: List[str]) -> Dict[str, Any]:
        """
        Internal execution helper executing strictly validated remediation commands.
        """
        if len(args) < 3 or args[0] != "kubectl":
            raise PermissionError(f"Unauthorized command structure rejected: {args}")

        verb = args[1]
        if verb not in ("rollout", "scale", "get", "patch"):
            raise PermissionError(f"Unauthorized Kubernetes verb '{verb}' rejected by security boundary")

        try:
            res = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True,
            )
            if "-o" in args and "json" in args:
                return json.loads(res.stdout)
            return {"output": res.stdout.strip(), "success": True}
        except subprocess.CalledProcessError as e:
            logger.error(f"Controlled remediation command failed ({e.returncode}): {e.stderr}")
            raise RuntimeError(f"Kubernetes remediation failed: {e.stderr.strip()}")
        except Exception as e:
            logger.error(f"Remediation execution error: {str(e)}")
            raise

    def get_workload_snapshot(self, namespace: str, deployment: str) -> PreRemediationSnapshot:
        """
        Capture pre-remediation workload state for audit logging.
        """
        dep_data = self._execute_controlled_cmd(["kubectl", "get", "deployment", deployment, "-n", namespace, "-o", "json"])
        status = dep_data.get("status", {})
        spec = dep_data.get("spec", {})
        annotations = dep_data.get("metadata", {}).get("annotations", {})

        pod_data = self._execute_controlled_cmd(["kubectl", "get", "pods", "-n", namespace, "-l", f"app={deployment}", "-o", "json"])
        pod_items = pod_data.get("items", [])

        pod_restarts = {}
        container_statuses = {}
        for p in pod_items:
            p_name = p.get("metadata", {}).get("name", "unknown")
            c_statuses = p.get("status", {}).get("containerStatuses", [])
            total_restarts = sum(cs.get("restartCount", 0) for cs in c_statuses)
            pod_restarts[p_name] = total_restarts
            for cs in c_statuses:
                state_str = "Running" if cs.get("ready") else "NotReady"
                if "waiting" in cs.get("state", {}):
                    state_str = cs["state"]["waiting"].get("reason", "Waiting")
                elif "terminated" in cs.get("state", {}):
                    state_str = cs["state"]["terminated"].get("reason", "Terminated")
                container_statuses[p_name] = state_str

        containers = spec.get("template", {}).get("spec", {}).get("containers", [])
        image = containers[0].get("image") if containers else "unknown"
        revision = annotations.get("deployment.kubernetes.io/revision")

        return PreRemediationSnapshot(
            deployment_name=deployment,
            namespace=namespace,
            desired_replicas=spec.get("replicas", 0),
            available_replicas=status.get("availableReplicas", 0),
            ready_replicas=status.get("readyReplicas", 0),
            pod_count=len(pod_items),
            pod_restarts=pod_restarts,
            container_statuses=container_statuses,
            current_image=image,
            current_revision=revision,
            captured_at=datetime.now(timezone.utc).isoformat(),
        )

    def restart_deployment(self, namespace: str, deployment: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute rolling restart on deployment using native restart annotation patch.
        """
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        patch_payload = json.dumps({
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now_ts,
                            "agentops.io/restart-reason": reason or "Remediation rolling restart",
                        }
                    }
                }
            }
        })
        res = self._execute_controlled_cmd([
            "kubectl", "patch", "deployment", deployment, "-n", namespace,
            "--type=merge", "-p", patch_payload
        ])
        logger.info(f"Deployment '{deployment}' restarted in namespace '{namespace}'")
        return {"action": "restart", "deployment": deployment, "namespace": namespace, "restarted_at": now_ts, "details": res}

    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> Dict[str, Any]:
        """
        Scale deployment replicas safely.
        """
        if replicas < 1 or replicas > 20:
            raise ValueError(f"Replicas count {replicas} is outside safe bounds [1, 20]")

        patch_payload = json.dumps({"spec": {"replicas": replicas}})
        res = self._execute_controlled_cmd([
            "kubectl", "patch", "deployment", deployment, "-n", namespace,
            "--type=merge", "-p", patch_payload
        ])
        logger.info(f"Deployment '{deployment}' scaled to {replicas} replicas in namespace '{namespace}'")
        return {"action": "scale", "deployment": deployment, "namespace": namespace, "replicas": replicas, "details": res}

    def rollback_deployment(self, namespace: str, deployment: str, revision: Optional[int] = None) -> Dict[str, Any]:
        """
        Roll back deployment to a previous or specific revision.
        """
        cmd = ["kubectl", "rollout", "undo", f"deployment/{deployment}", "-n", namespace]
        if revision is not None and revision > 0:
            cmd.extend([f"--to-revision={revision}"])

        res = self._execute_controlled_cmd(cmd)
        logger.info(f"Deployment '{deployment}' rolled back in namespace '{namespace}' (revision: {revision})")
        return {"action": "rollback", "deployment": deployment, "namespace": namespace, "target_revision": revision, "details": res}

    def verify_workload_health(
        self,
        namespace: str,
        deployment: str,
        expected_replicas: Optional[int] = None,
        timeout_seconds: int = 120,
    ) -> RemediationVerification:
        """
        Verify post-remediation deployment rollout and pod readiness.
        """
        start_time = time.time()
        checks = ["deployment_exists", "rollout_complete", "replicas_ready"]
        failed_checks = []
        observations = {}

        while time.time() - start_time < timeout_seconds:
            try:
                dep_data = self._execute_controlled_cmd(["kubectl", "get", "deployment", deployment, "-n", namespace, "-o", "json"])
                status = dep_data.get("status", {})
                spec = dep_data.get("spec", {})

                desired = expected_replicas if expected_replicas is not None else spec.get("replicas", 1)
                available = status.get("availableReplicas", 0)
                ready = status.get("readyReplicas", 0)
                updated = status.get("updatedReplicas", 0)

                observations["desired_replicas"] = desired
                observations["available_replicas"] = available
                observations["ready_replicas"] = ready
                observations["updated_replicas"] = updated

                if expected_replicas is not None:
                    # Precise replica count convergence for scale operations
                    if available == desired and ready == desired and updated == desired:
                        return RemediationVerification(
                            healthy=True,
                            checks=checks,
                            failed_checks=[],
                            observations=observations,
                            verified_at=datetime.now(timezone.utc).isoformat(),
                        )
                else:
                    # General convergence for restart / rollback
                    if available >= desired and ready >= desired and updated >= desired:
                        return RemediationVerification(
                            healthy=True,
                            checks=checks,
                            failed_checks=[],
                            observations=observations,
                            verified_at=datetime.now(timezone.utc).isoformat(),
                        )
            except Exception as e:
                observations["error"] = str(e)

            time.sleep(2)

        # Timeout reached
        failed_checks.append("rollout_timeout")
        return RemediationVerification(
            healthy=False,
            checks=checks,
            failed_checks=failed_checks,
            observations=observations,
            verified_at=datetime.now(timezone.utc).isoformat(),
        )
