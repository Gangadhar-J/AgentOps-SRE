import json
import logging
import subprocess
from typing import Any, Dict, List, Optional
from agentops.config import settings

logger = logging.getLogger("agentops.kubernetes")


class KubernetesInvestigationClient:
    """
    STRICTLY READ-ONLY Kubernetes Client for incident investigation.
    
    Security Guarantee:
    This client exclusively implements inspection methods ('get' and 'list').
    It exposes ZERO mutation, write, patch, scale, restart, delete, or exec methods.
    """

    def __init__(self, timeout: Optional[int] = None):
        self.timeout = timeout or settings.TELEMETRY_TIMEOUT_SECONDS

    def _run_read_only_cmd(self, args: List[str]) -> Dict[str, Any]:
        """
        Internal helper executing strictly validated read-only kubectl commands.
        """
        if len(args) < 2 or args[0] != "kubectl" or args[1] not in ("get", "version", "cluster-info"):
            raise PermissionError(f"Unauthorized command rejected by read-only security boundary: {args}")

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
            return {"raw_output": res.stdout}
        except subprocess.CalledProcessError as e:
            logger.error(f"kubectl command failed ({e.returncode}): {e.stderr}")
            raise
        except Exception as e:
            logger.error(f"Kubernetes inspection failed: {str(e)}")
            raise

    def is_available(self) -> bool:
        try:
            self._run_read_only_cmd(["kubectl", "version", "--client", "-o", "json"])
            return True
        except Exception:
            return False

    def get_pods(self, namespace: str, label_selector: Optional[str] = None) -> List[Dict[str, Any]]:
        cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "json"]
        if label_selector:
            cmd.extend(["-l", label_selector])
        data = self._run_read_only_cmd(cmd)
        items = data.get("items", [])
        # Filter out terminating pods whose deletion timestamp is set
        return [p for p in items if not p.get("metadata", {}).get("deletionTimestamp")]

    def get_deployment(self, name: str, namespace: str) -> Optional[Dict[str, Any]]:
        try:
            return self._run_read_only_cmd(["kubectl", "get", "deployment", name, "-n", namespace, "-o", "json"])
        except Exception:
            return None

    def get_pod_health_summaries(self, namespace: str, label_selector: Optional[str] = None) -> List[Dict[str, Any]]:
        pods = self.get_pods(namespace, label_selector)
        summaries = []
        for pod in pods:
            metadata = pod.get("metadata", {})
            status = pod.get("status", {})
            container_statuses = status.get("containerStatuses", [])
            
            restarts = 0
            is_ready = False
            state_reason = "Running"
            last_termination_reason = None
            last_exit_code = None

            for cs in container_statuses:
                restarts += cs.get("restartCount", 0)
                if cs.get("ready"):
                    is_ready = True
                
                state = cs.get("state", {})
                if "waiting" in state:
                    state_reason = state["waiting"].get("reason", "Waiting")
                elif "terminated" in state:
                    state_reason = state["terminated"].get("reason", "Terminated")

                last_state = cs.get("lastState", {})
                if "terminated" in last_state:
                    last_termination_reason = last_state["terminated"].get("reason")
                    last_exit_code = last_state["terminated"].get("exitCode")

            summaries.append({
                "pod_name": metadata.get("name"),
                "phase": status.get("phase"),
                "is_ready": is_ready,
                "restart_count": restarts,
                "current_state_reason": state_reason,
                "last_termination_reason": last_termination_reason,
                "last_exit_code": last_exit_code,
                "node_name": pod.get("spec", {}).get("nodeName"),
            })
        return summaries

    def get_warning_events(self, namespace: str, limit: int = 30) -> List[Dict[str, Any]]:
        try:
            data = self._run_read_only_cmd([
                "kubectl", "get", "events", "-n", namespace,
                "--sort-by=.metadata.creationTimestamp", "-o", "json"
            ])
            items = data.get("items", [])
            warning_events = []
            for item in items[-limit:]:
                event_type = item.get("type", "Normal")
                reason = item.get("reason", "Unknown")
                involved = item.get("involvedObject", {})
                warning_events.append({
                    "type": event_type,
                    "reason": reason,
                    "message": item.get("message", ""),
                    "object_kind": involved.get("kind"),
                    "object_name": involved.get("name"),
                    "count": item.get("count", 1),
                    "last_timestamp": item.get("lastTimestamp") or item.get("eventTime") or "",
                })
            return warning_events
        except Exception:
            return []
