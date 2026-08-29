import logging
import time
from typing import Any, Dict, List, Optional
import requests
from agentops.config import settings

logger = logging.getLogger("agentops.prometheus")


class PrometheusClient:
    """
    Read-only HTTP client for querying Prometheus metrics.
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

    def query_range(
        self, query: str, start: float, end: float, step: str = "15s"
    ) -> Dict[str, Any]:
        """
        Execute a range PromQL query (/api/v1/query_range).
        """
        params = {
            "query": query,
            "start": start,
            "end": end,
            "step": step,
        }
        try:
            res = requests.get(
                f"{self.base_url}/api/v1/query_range",
                params=params,
                timeout=self.timeout,
            )
            res.raise_for_status()
            data = res.json()
            if data.get("status") == "success":
                return data.get("data", {})
            return {}
        except Exception as e:
            logger.error(f"Prometheus range query failed for '{query}': {str(e)}")
            raise

    def get_http_error_rate(self, app: str, namespace: str = "demo") -> Optional[float]:
        """
        Calculate error rate percentage (status 5xx / total requests * 100).
        """
        query = (
            f'sum(rate(http_requests_total{{app="{app}", namespace="{namespace}", status=~"5.."}}[2m])) '
            f'/ sum(rate(http_requests_total{{app="{app}", namespace="{namespace}"}}[2m])) * 100'
        )
        data = self.query_instant(query)
        result = data.get("result", [])
        if result and len(result) > 0:
            val = result[0].get("value", [None, None])[1]
            if val is not None and val != "NaN":
                return round(float(val), 2)
        return None

    def get_http_requests_summary(self, app: str, namespace: str = "demo") -> List[Dict[str, Any]]:
        """
        Get request counts grouped by endpoint and status code.
        """
        query = f'sum by (endpoint, status) (http_requests_total{{app="{app}", namespace="{namespace}"}})'
        data = self.query_instant(query)
        results = []
        for item in data.get("result", []):
            metric = item.get("metric", {})
            value = item.get("value", [None, 0])[1]
            results.append({
                "endpoint": metric.get("endpoint", "unknown"),
                "status": metric.get("status", "unknown"),
                "count": int(float(value)) if value else 0,
            })
        return results

    def get_synthetic_memory_allocation_mb(self, app: str) -> Optional[float]:
        """
        Get synthetic memory leak allocation in MB.
        """
        query = f'app_memory_allocated_bytes{{app="{app}"}}'
        data = self.query_instant(query)
        result = data.get("result", [])
        if result and len(result) > 0:
            val = result[0].get("value", [None, None])[1]
            if val is not None:
                return round(float(val) / (1024 * 1024), 2)
        return None
