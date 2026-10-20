import json
import logging
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime
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
        if len(args) < 2 or args[0] != "kubectl":
            raise PermissionError(f"Unauthorized command rejected by read-only security boundary: {args}")

        subcmd = args[1]
        if subcmd not in ("get", "version", "cluster-info", "config"):
            raise PermissionError(f"Unauthorized command rejected by read-only security boundary: {args}")

        if subcmd == "config":
            if len(args) < 3 or args[2] not in ("current-context", "view"):
                raise PermissionError(f"Unauthorized kubectl config operation: {args}")

        env = os.environ.copy()
        if settings.KUBECONFIG_PATH and Path(settings.KUBECONFIG_PATH).exists():
            env["KUBECONFIG"] = str(settings.KUBECONFIG_PATH)

        try:
            res = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True,
                env=env,
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

    def get_auth_mode(self) -> str:
        """Report active Kubernetes authentication mechanism."""
        if Path("/var/run/secrets/kubernetes.io/serviceaccount").exists() or "KUBERNETES_SERVICE_HOST" in os.environ:
            return "IN_CLUSTER"
        if os.getenv("KUBECONFIG"):
            return "KUBECONFIG_ENV"
        if settings.KUBECONFIG_PATH and Path(settings.KUBECONFIG_PATH).exists():
            return "KUBECONFIG_FILE"
        return "DEFAULT"

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Discover cluster nodes and readiness conditions (Read-Only)."""
        data = self._run_read_only_cmd(["kubectl", "get", "nodes", "-o", "json"])
        items = data.get("items", [])
        nodes = []
        for n in items:
            meta = n.get("metadata", {})
            status = n.get("status", {})
            conditions = status.get("conditions", [])
            ready_cond = next((c for c in conditions if c.get("type") == "Ready"), {})
            is_ready = ready_cond.get("status") == "True"
            node_info = status.get("nodeInfo", {})
            nodes.append({
                "name": meta.get("name"),
                "ready": is_ready,
                "condition_reason": ready_cond.get("reason", "Unknown"),
                "kubelet_version": node_info.get("kubeletVersion", "unknown"),
                "os_image": node_info.get("osImage", "unknown"),
                "architecture": node_info.get("architecture", "unknown"),
            })
        return nodes

    def get_cluster_overview(self) -> Dict[str, Any]:
        """Aggregate high-level cluster health, context, and topology."""
        auth_mode = self.get_auth_mode()
        connected = False
        nodes = []
        namespaces = []
        context_name = "unknown"
        error = None

        try:
            nodes = self.get_nodes()
            namespaces = self.get_namespaces()
            connected = True
            try:
                ctx_data = self._run_read_only_cmd(["kubectl", "config", "current-context"])
                context_name = ctx_data.get("raw_output", "unknown").strip()
            except Exception:
                context_name = "connected-cluster"
        except Exception as e:
            error = str(e)

        return {
            "connected": connected,
            "auth_mode": auth_mode,
            "current_context": context_name,
            "nodes_count": len(nodes),
            "nodes_ready": sum(1 for n in nodes if n.get("ready")),
            "nodes": nodes,
            "namespaces_count": len(namespaces),
            "namespaces": namespaces,
            "error": error,
        }

    def get_namespaces(self) -> List[str]:
        """
        Discover active cluster namespaces (Read-Only).
        Raises exception if cluster query fails.
        """
        data = self._run_read_only_cmd(["kubectl", "get", "namespaces", "-o", "json"])
        items = data.get("items", [])
        return [
            ns.get("metadata", {}).get("name")
            for ns in items
            if ns.get("metadata", {}).get("name")
        ]

    def get_deployments(self, namespace: str) -> List[Dict[str, Any]]:
        """
        Discover active deployments in a namespace (Read-Only).
        Raises exception if cluster query fails.
        """
        data = self._run_read_only_cmd(["kubectl", "get", "deployments", "-n", namespace, "-o", "json"])
        items = data.get("items", [])
        deployments = []
        for dep in items:
            meta = dep.get("metadata", {})
            spec = dep.get("spec", {})
            status = dep.get("status", {})
            deployments.append({
                "name": meta.get("name"),
                "namespace": namespace,
                "desired_replicas": spec.get("replicas", 0),
                "ready_replicas": status.get("readyReplicas", 0),
                "available_replicas": status.get("availableReplicas", 0),
                "updated_replicas": status.get("updatedReplicas", 0),
                "created_at": meta.get("creationTimestamp"),
            })
        return deployments

    def get_pods(self, namespace: str, label_selector: Optional[str] = None) -> List[Dict[str, Any]]:
        cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "json"]
        if label_selector:
            cmd.extend(["-l", label_selector])
        data = self._run_read_only_cmd(cmd)
        items = data.get("items", [])
        return [p for p in items if not p.get("metadata", {}).get("deletionTimestamp")]

    def get_deployment(self, name: str, namespace: str) -> Optional[Dict[str, Any]]:
        try:
            return self._run_read_only_cmd(["kubectl", "get", "deployment", name, "-n", namespace, "-o", "json"])
        except Exception:
            return None

    def get_deployment_summary(self, name: str, namespace: str) -> Dict[str, Any]:
        dep = self.get_deployment(name, namespace)
        if not dep:
            return {"found": False, "deployment": name, "namespace": namespace}

        status = dep.get("status", {})
        spec = dep.get("spec", {})
        return {
            "found": True,
            "deployment": name,
            "namespace": namespace,
            "desired_replicas": spec.get("replicas", 0),
            "ready_replicas": status.get("readyReplicas", 0),
            "available_replicas": status.get("availableReplicas", 0),
            "unavailable_replicas": status.get("unavailableReplicas", 0),
            "updated_replicas": status.get("updatedReplicas", 0),
            "conditions": status.get("conditions", []),
        }

    def get_pod_health_summaries(
        self, namespace: str, label_selector: Optional[str] = None, pod_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        pods = self.get_pods(namespace, label_selector)
        if pod_name:
            pods = [p for p in pods if p.get("metadata", {}).get("name") == pod_name]

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
                "namespace": namespace,
                "phase": status.get("phase"),
                "is_ready": is_ready,
                "restart_count": restarts,
                "current_state_reason": state_reason,
                "last_termination_reason": last_termination_reason,
                "last_exit_code": last_exit_code,
                "node_name": pod.get("spec", {}).get("nodeName"),
            })
        return summaries

    def get_warning_events(
        self, namespace: str, limit: int = 30, resource_name: Optional[str] = None, lookback_seconds: int = 180
    ) -> List[Dict[str, Any]]:
        try:
            data = self._run_read_only_cmd([
                "kubectl", "get", "events", "-n", namespace,
                "--sort-by=.metadata.creationTimestamp", "-o", "json"
            ])
            items = data.get("items", [])
            warning_events = []
            now_ts = time.time()

            for item in items:
                involved = item.get("involvedObject", {})
                obj_name = involved.get("name", "")
                if resource_name and resource_name not in obj_name:
                    continue

                ts_str = item.get("lastTimestamp") or item.get("eventTime") or ""
                if ts_str:
                    try:
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if (now_ts - dt.timestamp()) > lookback_seconds:
                            continue
                    except Exception:
                        pass

                event_type = item.get("type", "Normal")
                reason = item.get("reason", "Unknown")
                warning_events.append({
                    "type": event_type,
                    "reason": reason,
                    "message": item.get("message", ""),
                    "object_kind": involved.get("kind"),
                    "object_name": obj_name,
                    "count": item.get("count", 1),
                    "last_timestamp": ts_str,
                })
            return warning_events[-limit:]
        except Exception:
            return []
