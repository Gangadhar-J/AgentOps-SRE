import logging
import time
from typing import Any, Dict, List, Optional
import requests
from agentops.config import settings

logger = logging.getLogger("agentops.prometheus")


class PrometheusClient:
    """
    Read-only HTTP client for querying real Prometheus metrics.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        self.base_url = (base_url or settings.PROMETHEUS_URL).rstrip("/")
        self.timeout = timeout or settings.TELEMETRY_TIMEOUT_SECONDS

    def is_available(self) -> bool:
        try:
            res = requests.get(f"{self.base_url}/-/healthy", timeout=self.timeout)
            return res.status_code == 200
        except Exception:
            return False

    def query_instant(self, query: str, timestamp: Optional[float] = None) -> Dict[str, Any]:
        """
        Execute an instant PromQL query (/api/v1/query).
        """
        params: Dict[str, Any] = {"query": query}
        if timestamp:
            params["time"] = timestamp

        try:
            res = requests.get(
                f"{self.base_url}/api/v1/query",
                params=params,
                timeout=self.timeout,
            )
            res.raise_for_status()
            data = res.json()
            if data.get("status") == "success":
                return data.get("data", {})
            logger.warning(f"Prometheus query returned status: {data.get('status')}")
            return {}
        except Exception as e:
            logger.error(f"Prometheus query failed for '{query}': {str(e)}")
            raise

    def get_http_error_rate(self, app: str, namespace: str = "demo", duration: str = "2m") -> Optional[float]:
        """
        Calculate error rate percentage from real http_requests_total (status 5xx / total requests * 100).
        """
        query = (
            f'sum(rate(http_requests_total{{app="{app}", namespace="{namespace}", status=~"5.."}}[{duration}])) '
            f'/ sum(rate(http_requests_total{{app="{app}", namespace="{namespace}"}}[{duration}])) * 100'
        )
        try:
            data = self.query_instant(query)
            result = data.get("result", [])
            if result and len(result) > 0:
                val = result[0].get("value", [None, None])[1]
                if val is not None and val != "NaN":
                    return round(float(val), 2)
            return None
        except Exception:
            return None

    def get_http_latency_p95(self, app: str, namespace: str = "demo", duration: str = "5m") -> Optional[float]:
        """
        Calculate 95th percentile request latency from real histogram buckets.
        """
        query = f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{app="{app}", namespace="{namespace}"}}[{duration}])) by (le))'
        try:
            data = self.query_instant(query)
            result = data.get("result", [])
            if result and len(result) > 0:
                val = result[0].get("value", [None, None])[1]
                if val is not None and val != "NaN":
                    return round(float(val), 4)
            return None
        except Exception:
            return None

    def get_memory_usage(self, app: str, namespace: str = "demo") -> Dict[str, Any]:
        """
        Query real memory metrics (process_resident_memory_bytes or container memory) from Prometheus.
        """
        query = f'process_resident_memory_bytes{{app="{app}", namespace="{namespace}"}}'
        try:
            data = self.query_instant(query)
            result = data.get("result", [])
            if not result:
                # Fallback to app_memory_allocated_bytes if scraped
                fallback_query = f'app_memory_allocated_bytes{{app="{app}", namespace="{namespace}"}}'
                data = self.query_instant(fallback_query)
                result = data.get("result", [])

            pod_metrics = []
            max_mb = 0.0
            metric_name = "unknown"
            ts = None

            for entry in result:
                m = entry.get("metric", {})
                metric_name = m.get("__name__", "memory_bytes")
                val_tuple = entry.get("value", [None, None])
                ts = val_tuple[0]
                raw_bytes = float(val_tuple[1]) if val_tuple[1] is not None else 0.0
                mb = round(raw_bytes / (1024 * 1024), 2)
                if mb > max_mb:
                    max_mb = mb
                pod_metrics.append({
                    "pod": m.get("pod", "unknown"),
                    "node": m.get("node", "unknown"),
                    "memory_bytes": int(raw_bytes),
                    "memory_mb": mb,
                })

            return {
                "app": app,
                "namespace": namespace,
                "metric_name": metric_name,
                "timestamp": ts,
                "pods": pod_metrics,
                "max_memory_mb": max_mb if pod_metrics else None,
            }
        except Exception as e:
            logger.error(f"Prometheus memory query failed: {str(e)}")
            return {
                "app": app,
                "namespace": namespace,
                "metric_name": "error",
                "pods": [],
                "max_memory_mb": None,
                "error": str(e),
            }
