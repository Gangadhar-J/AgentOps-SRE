import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional
import requests

from flask import Flask, jsonify, render_template, request

from agentops.clients.kubernetes import KubernetesInvestigationClient
from agentops.clients.loki import LokiClient
from agentops.clients.prometheus import PrometheusClient
from agentops.config import settings
from agentops.incident.orchestrator import IncidentWorkflowManager
from evaluation.baseline import BaselineManager

logger = logging.getLogger("agentops.api")

ALLOWED_DEMO_SCENARIOS = {
    "crashloop",
    "high-error-rate",
    "resource-exhaustion",
    "bad-deployment",
    "reset",
}


def create_app(workflow_manager: Optional[IncidentWorkflowManager] = None) -> Flask:
    """
    Application factory for the AgentOps SRE Operator Console & REST API.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(base_dir, "templates")
    static_dir = os.path.join(base_dir, "static")

    app = Flask(
        __name__,
        template_folder=templates_dir,
        static_folder=static_dir,
    )

    workflow = workflow_manager or IncidentWorkflowManager()
    project_root = os.path.dirname(os.path.dirname(base_dir))

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/status", methods=["GET"])
    def get_status():
        # 1. Kubernetes check
        k8s_connected = False
        k8s_info = "Disconnected / Local"
        k8s_ns_count = 0
        try:
            k8s = KubernetesInvestigationClient()
            if k8s.is_available():
                namespaces = k8s.get_namespaces()
                k8s_connected = True
                k8s_ns_count = len(namespaces)
                k8s_info = f"Connected ({k8s_ns_count} namespaces)"
            else:
                k8s_info = "Kubernetes unreachable (kubectl check failed)"
        except Exception as e:
            k8s_info = f"Kubernetes check error: {str(e)}"

        # 2. Prometheus check
        prom_connected = False
        try:
            prom = PrometheusClient()
            prom_connected = prom.is_available()
        except Exception:
            prom_connected = False

        # 3. Loki check
        loki_connected = False
        try:
            loki = LokiClient()
            loki_connected = loki.is_available()
        except Exception:
            loki_connected = False

        # 4. Grafana check
        grafana_connected = False
        try:
            res = requests.get(f"{settings.GRAFANA_URL}/api/health", timeout=1.5)
            grafana_connected = res.status_code == 200
        except Exception:
            grafana_connected = False

        # 5. Ollama check
        ollama_connected = False
        ollama_model_count = 0
        try:
            res = requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=1.5)
            if res.status_code == 200:
                ollama_connected = True
                models = res.json().get("models", [])
                ollama_model_count = len(models)
        except Exception:
            ollama_connected = False

        active_inc = workflow.get_active_incident()
        last_exec = workflow.get_last_execution()
        pending_apps = workflow.get_pending_approvals()

        return jsonify(
            {
                "status": "ok",
                "version": "0.7.1",
                "components": {
                    "kubernetes": {
                        "connected": k8s_connected,
                        "info": k8s_info,
                        "namespace_count": k8s_ns_count,
                    },
                    "prometheus": {
                        "connected": prom_connected,
                        "url": settings.PROMETHEUS_URL,
                    },
                    "loki": {
                        "connected": loki_connected,
                        "url": settings.LOKI_URL,
                    },
                    "grafana": {
                        "connected": grafana_connected,
                        "url": settings.GRAFANA_URL,
                    },
                    "ollama": {
                        "connected": ollama_connected,
                        "url": settings.OLLAMA_URL,
                        "model_count": ollama_model_count,
                    },
                },
                "cluster": {
                    "connected": k8s_connected,
                    "info": k8s_info,
                },
                "active_incident": active_inc.model_dump() if active_inc else None,
                "pending_approvals_count": len(pending_apps),
                "pending_approvals": pending_apps,
                "last_execution": last_exec.model_dump() if last_exec else None,
            }
        )

    @app.route("/api/cluster/namespaces", methods=["GET"])
    def get_cluster_namespaces():
        try:
            k8s = KubernetesInvestigationClient()
            namespaces = k8s.get_namespaces()
            return jsonify({
                "status": "ok",
                "namespaces": namespaces,
                "count": len(namespaces),
            }), 200
        except Exception as e:
            logger.warning(f"Failed to fetch cluster namespaces: {e}")
            fallback = ["demo", "default", "kube-system"]
            return jsonify({
                "status": "partial",
                "namespaces": fallback,
                "count": len(fallback),
                "error": str(e),
            }), 200

    @app.route("/api/cluster/workloads", methods=["GET"])
    def get_cluster_workloads():
        namespace = request.args.get("namespace", "demo")
        try:
            k8s = KubernetesInvestigationClient()
            deployments = k8s.get_deployments(namespace=namespace)
            workload_names = [d.get("name") for d in deployments if d.get("name")]
            return jsonify({
                "status": "ok",
                "namespace": namespace,
                "workloads": workload_names,
                "deployments": deployments,
                "count": len(workload_names),
            }), 200
        except Exception as e:
            logger.warning(f"Failed to fetch workloads for namespace '{namespace}': {e}")
            fallback = ["demo-app"] if namespace == "demo" else []
            return jsonify({
                "status": "partial",
                "namespace": namespace,
                "workloads": fallback,
                "deployments": [],
                "count": len(fallback),
                "error": str(e),
            }), 200

    @app.route("/api/telemetry/pulse", methods=["GET"])
    def get_telemetry_pulse():
        """
        STRICTLY READ-ONLY telemetry pulse for real-time observability.
        Never produces ActionRequests, approvals, or evaluations.
        """
        namespace = request.args.get("namespace", "demo")
        workload = request.args.get("workload", "demo-app")

        k8s = KubernetesInvestigationClient()
        prom = PrometheusClient()

        # 1. Kubernetes health signals
        dep_summary = k8s.get_deployment_summary(name=workload, namespace=namespace)
        pods = k8s.get_pod_health_summaries(namespace=namespace, label_selector=f"app={workload}")
        warning_events = k8s.get_warning_events(namespace=namespace, resource_name=workload, limit=5)

        total_restarts = sum(p.get("restart_count", 0) for p in pods)
        ready_pods = sum(1 for p in pods if p.get("is_ready"))
        desired_replicas = dep_summary.get("desired_replicas", len(pods))

        # 2. Prometheus telemetry metrics
        error_rate = None
        p95_latency = None
        memory_mb = None
        prom_connected = prom.is_available()
        if prom_connected:
            try:
                error_rate = prom.get_http_error_rate(app=workload, namespace=namespace)
                p95_latency = prom.get_http_latency_p95(app=workload, namespace=namespace)
                mem_data = prom.get_memory_usage(app=workload, namespace=namespace)
                memory_mb = mem_data.get("max_memory_mb")
            except Exception as e:
                logger.debug(f"Prometheus pulse query exception: {e}")

        # 3. Overall pulse status: healthy / degraded / critical / unknown
        pulse_status = "healthy"
        reasons = []

        if not dep_summary.get("found") and not pods:
            pulse_status = "unknown"
            reasons.append(f"Workload '{workload}' not found in '{namespace}'")
        else:
            if desired_replicas > 0 and ready_pods == 0:
                pulse_status = "critical"
                reasons.append(f"0/{desired_replicas} pods ready")
            elif ready_pods < desired_replicas:
                pulse_status = "degraded"
                reasons.append(f"{ready_pods}/{desired_replicas} pods ready")

            for p in pods:
                state = p.get("current_state_reason", "")
                if state in ("CrashLoopBackOff", "Error", "OOMKilled", "ImagePullBackOff"):
                    pulse_status = "critical"
                    reasons.append(f"Pod {p.get('pod_name')}: {state}")
                    break

            if error_rate is not None and error_rate > 5.0:
                if error_rate > 20.0:
                    pulse_status = "critical"
                elif pulse_status != "critical":
                    pulse_status = "degraded"
                reasons.append(f"High HTTP error rate: {error_rate:.1f}%")

            if total_restarts > 0 and pulse_status == "healthy":
                pulse_status = "degraded"
                reasons.append(f"{total_restarts} pod restart(s) detected")

        return jsonify({
            "status": "ok",
            "namespace": namespace,
            "workload": workload,
            "pulse_status": pulse_status,
            "reasons": reasons,
            "k8s": {
                "desired_replicas": desired_replicas,
                "ready_pods": ready_pods,
                "total_restarts": total_restarts,
                "pods": pods,
                "warnings_count": len(warning_events),
                "recent_warnings": [w.get("message") for w in warning_events[:3]],
            },
            "prometheus": {
                "connected": prom_connected,
                "error_rate_pct": error_rate,
                "p95_latency_s": p95_latency,
                "memory_mb": memory_mb,
            },
            "deep_links": {
                "prometheus": f"{settings.PROMETHEUS_URL}/graph?g0.expr=rate(http_requests_total%7Bapp%3D%22{workload}%22%7D%5B2m%5D)",
                "grafana": f"{settings.GRAFANA_URL}",
            },
            "timestamp": time.time(),
        }), 200

    @app.route("/api/llm/models", methods=["GET"])
    def get_llm_models():
        """
        Discover available LLM models across local Ollama and optional cloud APIs.
        """
        ollama_url = settings.OLLAMA_URL.rstrip("/")
        ollama_available = False
        ollama_models = []
        ollama_error = None

        try:
            res = requests.get(f"{ollama_url}/api/tags", timeout=1.5)
            if res.status_code == 200:
                ollama_available = True
                data = res.json()
                for m in data.get("models", []):
                    details = m.get("details", {})
                    ollama_models.append({
                        "name": m.get("name"),
                        "model": m.get("model", m.get("name")),
                        "size_bytes": m.get("size", 0),
                        "parameter_size": details.get("parameter_size", "unknown"),
                        "quantization": details.get("quantization_level", "unknown"),
                        "family": details.get("family", "unknown"),
                        "modified_at": m.get("modified_at"),
                    })
        except Exception as e:
            ollama_error = str(e)

        cloud_providers = []
        if os.getenv("OPENAI_API_KEY"):
            cloud_providers.append({"provider": "openai", "name": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini"]})
        if os.getenv("GEMINI_API_KEY"):
            cloud_providers.append({"provider": "gemini", "name": "Google Gemini", "models": ["gemini-2.5-pro", "gemini-2.5-flash"]})
        if os.getenv("ANTHROPIC_API_KEY"):
            cloud_providers.append({"provider": "anthropic", "name": "Anthropic Claude", "models": ["claude-3-5-sonnet"]})

        default_provider = "mock"
        default_model = None

        if ollama_available and ollama_models:
            default_provider = "ollama"
            names = [m["name"] for m in ollama_models]
            for pref in ["qwen3.5:2b", "granite4.1:3b", "qwen3.5:4b", "ministral-3:8b"]:
                if pref in names:
                    default_model = pref
                    break
            if not default_model:
                default_model = names[0]

        return jsonify({
            "status": "ok",
            "default": {
                "provider": default_provider,
                "model": default_model,
            },
            "ollama": {
                "available": ollama_available,
                "url": ollama_url,
                "models": ollama_models,
                "error": ollama_error,
            },
            "cloud": {
                "available": len(cloud_providers) > 0,
                "providers": cloud_providers,
            },
            "mock": {
                "available": True,
                "name": "Deterministic Mock / Fast Rule-Engine",
                "models": ["deterministic-evaluator"],
            },
        }), 200

    @app.route("/api/incidents/investigate", methods=["POST"])
    def investigate_incident():
        payload = request.get_json() or {}
        namespace = payload.get("namespace", "demo")
        workload = payload.get("workload", "demo-app")
        incident_description = payload.get("incident_description")
        provider = payload.get("provider", "mock")
        model = payload.get("model")
        dry_run = bool(payload.get("dry_run", False))
        source = payload.get("source", "MANUAL")
        if source not in ("MANUAL", "ALERT", "DEMO"):
            source = "MANUAL"

        try:
            report = workflow.investigate_and_recommend(
                namespace=namespace,
                workload=workload,
                incident_description=incident_description,
                provider_name=provider,
                model_name=model,
                dry_run=dry_run,
                source=source,
            )
            return jsonify(report.model_dump()), 200
        except Exception as e:
            logger.exception("Investigation failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/incidents/active", methods=["GET"])
    def get_active_incident():
        report = workflow.get_active_incident()
        if report:
            return jsonify(report.model_dump()), 200
        return jsonify({"active_incident": None}), 200

    @app.route("/api/approvals", methods=["GET"])
    def list_approvals():
        pending = workflow.get_pending_approvals()
        return jsonify({"approvals": pending}), 200

    @app.route("/api/approvals/<approval_id>/approve", methods=["POST"])
    def approve_remediation(approval_id: str):
        payload = request.get_json() or {}
        operator = payload.get("operator", "sre-operator")
        reason = payload.get("reason", "Operator verified RCA and authorized remediation via Web UI")

        try:
            summary = workflow.approve_and_execute(
                approval_id=approval_id,
                operator_name=operator,
                reason=reason,
            )
            return jsonify(summary.model_dump()), 200
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 404
        except Exception as e:
            logger.exception(f"Execution failed for approval {approval_id}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/approvals/<approval_id>/reject", methods=["POST"])
    def reject_remediation(approval_id: str):
        payload = request.get_json() or {}
        operator = payload.get("operator", "sre-operator")
        reason = payload.get("reason", "Operator rejected remediation via Web UI")

        try:
            result = workflow.reject(
                approval_id=approval_id,
                operator_name=operator,
                reason=reason,
            )
            return jsonify(result), 200
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 404
        except Exception as e:
            logger.exception(f"Rejection failed for approval {approval_id}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/demo/trigger", methods=["POST"])
    def trigger_demo():
        payload = request.get_json() or {}
        scenario = payload.get("scenario")
        if not scenario or scenario not in ALLOWED_DEMO_SCENARIOS:
            return (
                jsonify(
                    {
                        "error": f"Invalid or missing scenario. Allowed values: {sorted(list(ALLOWED_DEMO_SCENARIOS))}"
                    }
                ),
                400,
            )

        # Mode B Sandbox Isolation: Strictly restrict chaos triggers to demo/demo-app
        req_namespace = payload.get("namespace", "demo")
        req_workload = payload.get("workload", "demo-app")
        if req_namespace != "demo" or req_workload != "demo-app":
            return (
                jsonify(
                    {
                        "error": (
                            f"Chaos triggers are strictly restricted to namespace 'demo' and workload 'demo-app'. "
                            f"Target '{req_namespace}/{req_workload}' is protected from synthetic chaos."
                        )
                    }
                ),
                400,
            )

        script_path = os.path.join(project_root, "scripts", "trigger-incident.sh")
        if not os.path.exists(script_path):
            return jsonify({"error": f"Script not found at {script_path}"}), 500

        try:
            res = subprocess.run(
                [script_path, scenario],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=project_root,
            )
            return (
                jsonify(
                    {
                        "status": "ok" if res.returncode == 0 else "error",
                        "scenario": scenario,
                        "exit_code": res.returncode,
                        "stdout": res.stdout,
                        "stderr": res.stderr,
                    }
                ),
                200 if res.returncode == 0 else 500,
            )
        except subprocess.TimeoutExpired:
            return jsonify({"error": f"Scenario {scenario} trigger timed out"}), 504
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/eval/summary", methods=["GET"])
    def get_eval_summary():
        try:
            bm = BaselineManager()
            baseline = bm.load_baseline()
            return jsonify(
                {
                    "status": "ok",
                    "baseline_id": baseline.baseline_id,
                    "overall_score": baseline.overall_score,
                    "passing": baseline.overall_score >= 0.85,
                    "scenario_scores": baseline.scenario_scores,
                    "created_at": baseline.created_at,
                }
            )
        except Exception as e:
            return jsonify({"status": "unavailable", "error": str(e), "overall_score": None})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=8000, debug=True)
