import json
import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional
from flask import Flask, jsonify, render_template, request
import requests

from agentops.clients.kubernetes import KubernetesInvestigationClient
from agentops.clients.loki import LokiClient
from agentops.clients.prometheus import PrometheusClient
from agentops.config import settings
from agentops.incident.models import IncidentReport
from agentops.incident.orchestrator import IncidentOrchestrator as IncidentWorkflowManager
from evaluation.baseline import BaselineManager

logger = logging.getLogger("agentops.api")

ALLOWED_DEMO_SCENARIOS = {
    "crashloop",
    "high-error-rate",
    "resource-exhaustion",
    "bad-deployment",
    "reset",
}

# Validation patterns
_K8S_NAME_REGEX = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_MODEL_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.\:\/]{1,128}$")


def validate_k8s_name(name: str, field_name: str = "resource") -> str:
    if not name or len(name) > 63 or not _K8S_NAME_REGEX.match(name):
        raise ValueError(
            f"Invalid {field_name} name '{name}'. Must be lowercase alphanumeric with hyphens, max 63 characters."
        )
    return name


def validate_model_name(name: str) -> str:
    if not name or len(name) > 128 or not _MODEL_NAME_REGEX.match(name):
        raise ValueError(
            f"Invalid model identifier '{name}'. Must be alphanumeric with allowed provider punctuation (._-:/), max 128 characters."
        )
    return name


# In-memory bounded LLM execution history (up to 100 entries, FIFO)
_LLM_EXECUTION_HISTORY: List[Dict[str, Any]] = []


def _record_llm_execution(report: IncidentReport) -> None:
    if report.llm_runtime:
        entry = {
            "incident_id": report.incident_id,
            "timestamp": report.timestamp,
            "namespace": report.namespace,
            "workload": report.workload,
            "provider": report.llm_runtime.provider,
            "model": report.llm_runtime.model,
            "mode": report.llm_runtime.mode,
            "latency_seconds": report.llm_runtime.latency_seconds,
            "prompt_tokens": report.llm_runtime.prompt_tokens,
            "completion_tokens": report.llm_runtime.completion_tokens,
            "total_tokens": report.llm_runtime.total_tokens,
            "tokens_per_second": report.llm_runtime.tokens_per_second,
            "time_to_first_token": report.llm_runtime.time_to_first_token,
            "status": report.llm_runtime.status,
            "error_category": report.llm_runtime.error_category,
            "schema_validated": report.llm_runtime.schema_validated,
            "evidence_validated": report.llm_runtime.evidence_validated,
            "trace_id": report.llm_runtime.trace_id,
        }
        _LLM_EXECUTION_HISTORY.append(entry)
        if len(_LLM_EXECUTION_HISTORY) > 100:
            _LLM_EXECUTION_HISTORY.pop(0)


def create_app(workflow_manager: Optional[IncidentWorkflowManager] = None) -> Flask:
    base_dir = os.path.abspath(os.path.dirname(__file__))
    template_dir = os.path.join(base_dir, "templates")
    static_dir = os.path.join(base_dir, "static")

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
    )

    workflow = workflow_manager or IncidentWorkflowManager()
    project_root = os.path.dirname(os.path.dirname(base_dir))

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/status", methods=["GET"])
    def get_status():
        k8s_connected = False
        k8s_info = "Disconnected"
        k8s_ns_count = 0
        k8s_auth_mode = "UNKNOWN"
        try:
            k8s = KubernetesInvestigationClient()
            k8s_auth_mode = k8s.get_auth_mode()
            if k8s.is_available():
                namespaces = k8s.get_namespaces()
                k8s_connected = True
                k8s_ns_count = len(namespaces)
                k8s_info = f"Connected ({k8s_ns_count} namespaces, auth: {k8s_auth_mode})"
            else:
                k8s_info = "Kubernetes unreachable (kubectl check failed)"
        except Exception as e:
            k8s_info = f"Kubernetes check error: {str(e)}"

        prom_connected = False
        try:
            prom = PrometheusClient()
            prom_connected = prom.is_available()
        except Exception:
            prom_connected = False

        loki_connected = False
        try:
            loki = LokiClient()
            loki_connected = loki.is_available()
        except Exception:
            loki_connected = False

        grafana_connected = False
        try:
            res = requests.get(f"{settings.GRAFANA_URL}/api/health", timeout=1.5)
            grafana_connected = res.status_code == 200
        except Exception:
            grafana_connected = False

        ollama_connected = False
        ollama_model_count = 0
        try:
            res = requests.get(f"{settings.OLLAMA_URL.rstrip('/')}/api/tags", timeout=1.5)
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
                "version": "0.7.2",
                "components": {
                    "kubernetes": {
                        "connected": k8s_connected,
                        "info": k8s_info,
                        "namespace_count": k8s_ns_count,
                        "auth_mode": k8s_auth_mode,
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
                    "auth_mode": k8s_auth_mode,
                },
                "active_incident": active_inc.model_dump() if active_inc else None,
                "pending_approvals_count": len(pending_apps),
                "pending_approvals": pending_apps,
                "last_execution": last_exec.model_dump() if last_exec else None,
            }
        ), 200

    @app.route("/api/cluster/overview", methods=["GET"])
    def get_cluster_overview():
        try:
            k8s = KubernetesInvestigationClient()
            overview = k8s.get_cluster_overview()
            return jsonify({
                "status": "ok" if overview["connected"] else "disconnected",
                "cluster": overview,
            }), 200 if overview["connected"] else 503
        except Exception as e:
            logger.error(f"Failed to fetch cluster overview: {e}")
            return jsonify({
                "status": "error",
                "error": str(e),
                "cluster": {
                    "connected": False,
                    "auth_mode": "UNKNOWN",
                    "current_context": "unavailable",
                    "nodes_count": 0,
                    "nodes": [],
                    "namespaces_count": 0,
                    "namespaces": [],
                }
            }), 503

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
            logger.error(f"Failed to fetch cluster namespaces: {e}")
            return jsonify({
                "status": "error",
                "namespaces": [],
                "count": 0,
                "error": f"Failed to retrieve namespaces: {str(e)}",
            }), 503

    @app.route("/api/cluster/workloads", methods=["GET"])
    def get_cluster_workloads():
        raw_ns = request.args.get("namespace", "demo")
        try:
            namespace = validate_k8s_name(raw_ns, "namespace")
        except ValueError as ve:
            return jsonify({"status": "error", "error": str(ve)}), 400

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
            logger.error(f"Failed to fetch workloads for namespace '{namespace}': {e}")
            return jsonify({
                "status": "error",
                "namespace": namespace,
                "workloads": [],
                "deployments": [],
                "count": 0,
                "error": f"Failed to retrieve workloads for namespace '{namespace}': {str(e)}",
            }), 503

    @app.route("/api/cluster/pods", methods=["GET"])
    def get_cluster_pods():
        raw_ns = request.args.get("namespace", "demo")
        workload = request.args.get("workload")
        try:
            namespace = validate_k8s_name(raw_ns, "namespace")
            if workload:
                validate_k8s_name(workload, "workload")
        except ValueError as ve:
            return jsonify({"status": "error", "error": str(ve)}), 400

        try:
            k8s = KubernetesInvestigationClient()
            selector = f"app={workload}" if workload else None
            pods = k8s.get_pod_health_summaries(namespace=namespace, label_selector=selector)
            return jsonify({
                "status": "ok",
                "namespace": namespace,
                "workload": workload,
                "pods": pods,
                "count": len(pods),
            }), 200
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 503

    @app.route("/api/cluster/events", methods=["GET"])
    def get_cluster_events():
        raw_ns = request.args.get("namespace", "demo")
        workload = request.args.get("workload")
        try:
            namespace = validate_k8s_name(raw_ns, "namespace")
            if workload:
                validate_k8s_name(workload, "workload")
        except ValueError as ve:
            return jsonify({"status": "error", "error": str(ve)}), 400

        try:
            k8s = KubernetesInvestigationClient()
            events = k8s.get_warning_events(namespace=namespace, resource_name=workload, limit=30)
            return jsonify({
                "status": "ok",
                "namespace": namespace,
                "workload": workload,
                "events": events,
                "count": len(events),
            }), 200
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 503

    @app.route("/api/telemetry/pulse", methods=["GET"])
    def get_telemetry_pulse():
        raw_ns = request.args.get("namespace", "demo")
        raw_wl = request.args.get("workload", "demo-app")
        try:
            namespace = validate_k8s_name(raw_ns, "namespace")
            workload = validate_k8s_name(raw_wl, "workload")
        except ValueError as ve:
            return jsonify({"status": "error", "error": str(ve)}), 400

        k8s = KubernetesInvestigationClient()
        prom = PrometheusClient()

        dep_summary = k8s.get_deployment_summary(name=workload, namespace=namespace)
        pods = k8s.get_pod_health_summaries(namespace=namespace, label_selector=f"app={workload}")
        warning_events = k8s.get_warning_events(namespace=namespace, resource_name=workload, limit=5)

        total_restarts = sum(p.get("restart_count", 0) for p in pods)
        ready_pods = sum(1 for p in pods if p.get("is_ready"))
        desired_replicas = dep_summary.get("desired_replicas", 0)

        prom_connected = prom.is_available()
        error_rate = None
        p95_latency = None
        memory_mb = None

        if prom_connected:
            try:
                error_rate = prom.get_http_error_rate(app=workload, namespace=namespace)
                p95_latency = prom.get_http_latency_p95(app=workload, namespace=namespace)
                mem_data = prom.get_memory_usage(app=workload, namespace=namespace)
                memory_mb = mem_data.get("max_memory_mb")
            except Exception as e:
                logger.debug(f"Prometheus pulse query exception: {e}")

        pulse_status = "healthy"
        reasons = []

        if not dep_summary.get("found") and not pods:
            pulse_status = "unknown"
            reasons.append(f"Workload '{workload}' not found in namespace '{namespace}'")
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
        Discover available real LLM models across local Ollama and configured cloud APIs.
        MOCK providers are strictly excluded from production investigation choices.
        """
        ollama_url = settings.OLLAMA_URL.rstrip("/")
        ollama_available = False
        ollama_models = []
        ollama_error = None

        try:
            res = requests.get(f"{ollama_url}/api/tags", timeout=2.0)
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

        default_provider = "none"
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
        elif cloud_providers:
            default_provider = cloud_providers[0]["provider"]
            default_model = cloud_providers[0]["models"][0]

        mock_allowed = app.testing or os.getenv("ALLOW_MOCK_RCA") == "true"
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
                "available": mock_allowed,
                "name": "Deterministic Mock (Offline Test Double Only)",
                "models": ["deterministic-evaluator"] if mock_allowed else [],
            },
        }), 200

    @app.route("/api/llm/history", methods=["GET"])
    def get_llm_history():
        """Retrieve recent LLM runtime execution telemetry records."""
        return jsonify({
            "status": "ok",
            "history": list(reversed(_LLM_EXECUTION_HISTORY)),
            "count": len(_LLM_EXECUTION_HISTORY),
        }), 200

    @app.route("/api/incidents/investigate", methods=["POST"])
    def investigate_incident():
        payload = request.get_json() or {}
        raw_ns = payload.get("namespace", "demo")
        raw_wl = payload.get("workload", "demo-app")
        incident_description = payload.get("incident_description")
        provider = payload.get("provider", "ollama")
        model = payload.get("model")
        dry_run = bool(payload.get("dry_run", False))
        source = payload.get("source", "MANUAL")
        if source not in ("MANUAL", "ALERT", "DEMO"):
            source = "MANUAL"

        try:
            namespace = validate_k8s_name(raw_ns, "namespace")
            workload = validate_k8s_name(raw_wl, "workload")
            if model:
                model = validate_model_name(model)
        except ValueError as ve:
            return jsonify({"status": "error", "error": str(ve)}), 400

        # Reject mock provider in live investigations unless explicitly in test environment
        if provider == "mock" and not app.testing and source != "DEMO" and os.getenv("ALLOW_MOCK_RCA") != "true":
            return jsonify({
                "status": "error",
                "error": "Mock/Rule-based RCA generation is prohibited in live investigations. Select a real model (Ollama, OpenAI, or Gemini)."
            }), 400

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
            _record_llm_execution(report)
            return jsonify(report.model_dump()), 200
        except Exception as e:
            logger.exception("Investigation execution failed")
            return jsonify({
                "status": "error",
                "error": str(e),
                "error_category": getattr(e, "error_category", type(e).__name__),
            }), 500

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
                    "type": "OFFLINE_EVALUATION_DATA",
                    "baseline_id": baseline.baseline_id,
                    "overall_score": baseline.overall_score,
                    "passing": baseline.overall_score >= 0.85,
                    "scenario_scores": baseline.scenario_scores,
                    "created_at": baseline.created_at,
                }
            )
        except Exception as e:
            return jsonify({"status": "unavailable", "type": "OFFLINE_EVALUATION_DATA", "error": str(e), "overall_score": None})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=settings.AGENTOPS_HOST, port=settings.AGENTOPS_PORT, debug=True)
