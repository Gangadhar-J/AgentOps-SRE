from typing import Any, Dict, List, Optional
from agentops.clients.kubernetes import KubernetesInvestigationClient
from agentops.clients.prometheus import PrometheusClient
from agentops.clients.loki import LokiClient


class KubernetesInvestigationTools:
    """
    Structured investigation tool interface for Kubernetes state inspection.
    Designed for seamless future wrapping as MCP tools.
    """

    def __init__(self, client: Optional[KubernetesInvestigationClient] = None):
        self.client = client or KubernetesInvestigationClient()

    def get_pod_health(self, namespace: str, app: str) -> List[Dict[str, Any]]:
        return self.client.get_pod_health_summaries(namespace, label_selector=f"app={app}")

    def get_warning_events(self, namespace: str, limit: int = 30) -> List[Dict[str, Any]]:
        return self.client.get_warning_events(namespace, limit=limit)


class PrometheusInvestigationTools:
    """
    Structured investigation tool interface for metrics telemetry.
    Designed for seamless future wrapping as MCP tools.
    """

    def __init__(self, client: Optional[PrometheusClient] = None):
        self.client = client or PrometheusClient()

    def query_error_rate(self, app: str, namespace: str) -> Optional[float]:
        return self.client.get_http_error_rate(app=app, namespace=namespace)

    def query_request_summary(self, app: str, namespace: str) -> List[Dict[str, Any]]:
        return self.client.get_http_requests_summary(app=app, namespace=namespace)

    def query_synthetic_memory(self, app: str) -> Optional[float]:
        return self.client.get_synthetic_memory_allocation_mb(app=app)


class LokiInvestigationTools:
    """
    Structured investigation tool interface for log telemetry.
    Designed for seamless future wrapping as MCP tools.
    """

    def __init__(self, client: Optional[LokiClient] = None):
        self.client = client or LokiClient()

    def search_error_logs(self, namespace: str, app: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self.client.get_error_logs(namespace=namespace, app=app, limit=limit)

    def search_fatal_crashes(self, namespace: str, app: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.client.get_fatal_crash_logs(namespace=namespace, app=app, limit=limit)

    def search_memory_leaks(self, namespace: str, app: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.client.get_memory_leak_logs(namespace=namespace, app=app, limit=limit)
