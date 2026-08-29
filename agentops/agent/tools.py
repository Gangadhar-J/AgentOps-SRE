from typing import Any, Dict, List, Optional
from agentops.clients.kubernetes import KubernetesInvestigationClient
from agentops.clients.prometheus import PrometheusClient
from agentops.clients.loki import LokiClient


class KubernetesInvestigationTools:
    """
    Structured investigation tool interface for Kubernetes state inspection.
    Wrapped exclusively by MCP Server in v0.3.
    """

    def __init__(self, client: Optional[KubernetesInvestigationClient] = None):
        self.client = client or KubernetesInvestigationClient()

    def get_pod_health(
        self, namespace: str, app: Optional[str] = None, pod: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        label_sel = f"app={app}" if app else None
        return self.client.get_pod_health_summaries(namespace, label_selector=label_sel, pod_name=pod)

    def get_deployment_health(self, namespace: str, deployment: str) -> Dict[str, Any]:
        return self.client.get_deployment_summary(name=deployment, namespace=namespace)

    def get_warning_events(
        self, namespace: str, limit: int = 30, resource_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return self.client.get_warning_events(namespace, limit=limit, resource_name=resource_name)


class PrometheusInvestigationTools:
    """
    Structured investigation tool interface for metrics telemetry.
    Wrapped exclusively by MCP Server in v0.3.
    """

    def __init__(self, client: Optional[PrometheusClient] = None):
        self.client = client or PrometheusClient()

    def query_error_rate(self, app: str, namespace: str = "demo", duration: str = "2m") -> Dict[str, Any]:
        rate = self.client.get_http_error_rate(app=app, namespace=namespace, duration=duration)
        return {
            "app": app,
            "namespace": namespace,
            "time_window": duration,
            "error_rate_percentage": rate,
            "query": f"sum(rate(http_requests_total{{app='{app}', status=~'5..'}}[{duration}]))",
        }

    def query_latency(
        self, app: str, namespace: str = "demo", quantile: float = 0.95, duration: str = "5m"
    ) -> Dict[str, Any]:
        latency = self.client.get_http_latency_p95(app=app, namespace=namespace, duration=duration)
        return {
            "app": app,
            "namespace": namespace,
            "quantile": quantile,
            "duration": duration,
            "latency_seconds": latency,
            "query": f"histogram_quantile({quantile}, ...)",
        }

    def query_memory(self, app: str, namespace: str = "demo") -> Dict[str, Any]:
        return self.client.get_memory_usage(app=app, namespace=namespace)


class LokiInvestigationTools:
    """
    Structured investigation tool interface for log telemetry.
    Wrapped exclusively by MCP Server in v0.3.
    """

    def __init__(self, client: Optional[LokiClient] = None):
        self.client = client or LokiClient()

    def search_error_logs(
        self, namespace: str, app: str, lookback_seconds: int = 90, limit: int = 20
    ) -> List[Dict[str, Any]]:
        return self.client.get_error_logs(namespace=namespace, app=app, limit=limit, lookback_seconds=lookback_seconds)

    def search_fatal_crashes(
        self, namespace: str, app: str, lookback_seconds: int = 90, limit: int = 10
    ) -> List[Dict[str, Any]]:
        return self.client.get_fatal_crash_logs(namespace=namespace, app=app, limit=limit, lookback_seconds=lookback_seconds)

    def search_memory_leaks(
        self, namespace: str, app: str, lookback_seconds: int = 90, limit: int = 10
    ) -> List[Dict[str, Any]]:
        return self.client.get_memory_leak_logs(namespace=namespace, app=app, limit=limit, lookback_seconds=lookback_seconds)

    def search_by_request_id(
        self, request_id: str, namespace: str = "demo", lookback_minutes: int = 10, limit: int = 20
    ) -> List[Dict[str, Any]]:
        return self.client.get_logs_by_request_id(
            request_id=request_id, namespace=namespace, lookback_minutes=lookback_minutes, limit=limit
        )
